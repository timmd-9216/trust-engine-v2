# Arquitectura de Procesamiento de Posts y Jobs

Este documento describe en detalle la arquitectura del sistema de procesamiento de posts y jobs, incluyendo las validaciones y mecanismos de reintentos implementados.

## Tabla de Contenidos

1. [Visión General](#visión-general)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Procesamiento de Posts (Fase 1)](#procesamiento-de-posts-fase-1)
4. [Procesamiento de Jobs (Fase 2)](#procesamiento-de-jobs-fase-2)
5. [Validaciones](#validaciones)
6. [Mecanismos de Reintentos](#mecanismos-de-reintentos)
7. [Estados y Transiciones](#estados-y-transiciones)
8. [Manejo de Errores](#manejo-de-errores)
9. [Control de Cuotas](#control-de-cuotas)
10. [Flujos de Datos](#flujos-de-datos)

---

## Visión General

El sistema implementa un procesamiento asíncrono en dos fases para recolectar respuestas de posts de redes sociales utilizando la API de Information Tracer:

- **Fase 1 - Creación de Jobs (`/process-posts`)**: Envía posts a Information Tracer API y crea jobs pendientes
- **Fase 2 - Procesamiento de Jobs (`/process-jobs`)**: Verifica el estado de los jobs, obtiene resultados y los guarda en GCS

Este enfoque permite:
- ✅ Procesamiento rápido (submit inmediato sin esperar resultados)
- ✅ Procesamiento asíncrono (jobs se procesan en segundo plano)
- ✅ Resiliencia ante fallos (mecanismos de reintentos y validaciones)
- ✅ Control de cuotas (verificación antes de procesar)

---

## Arquitectura del Sistema

### Componentes Principales

```
┌─────────────────┐
│   Firestore     │
│                 │
│  Collection:    │
│  - posts        │
│  - pending_jobs │
└────────┬────────┘
         │
         │ (Consulta/Actualización)
         │
┌────────▼──────────────────────────────────────┐
│         Trust API (FastAPI)                   │
│                                                │
│  ┌──────────────────────────────────────┐    │
│  │  /process-posts                       │    │
│  │  - Query posts (status='noreplies')  │    │
│  │  - Submit a Information Tracer       │    │
│  │  - Save job_id en pending_jobs       │    │
│  └──────────────────────────────────────┘    │
│                                                │
│  ┌──────────────────────────────────────┐    │
│  │  /process-jobs                       │    │
│  │  - Query pending_jobs                │    │
│  │  - Check status en Information Tracer│    │
│  │  - Get results                       │    │
│  │  - Save to GCS                       │    │
│  │  - Update status                     │    │
│  └──────────────────────────────────────┘    │
└────────┬──────────────────────────────────────┘
         │
         │ (API Calls)
         │
┌────────▼────────────┐
│ Information Tracer  │
│       API           │
│  - Submit           │
│  - Check Status     │
│  - Get Result       │
└─────────────────────┘
         │
         │ (Save Results)
         │
┌────────▼────────────┐
│   Google Cloud      │
│     Storage         │
│  (raw/ layer)       │
│  country/platform/  │
│  candidate_id/      │
│  {post_id}.json     │
└─────────────────────┘
```

### Flujo General

```
1. Posts en Firestore (status='noreplies')
   ↓
2. /process-posts → Submit a Information Tracer
   ↓
3. Job creado en pending_jobs (status='pending')
   ↓
4. Information Tracer procesa job (asíncrono)
   ↓
5. /process-jobs → Check status
   ↓
6a. Si finished → Get result → Save to GCS → status='done'
6b. Si failed → status='failed' o 'quota_exceeded'
6c. Si empty_result → status='empty_result'
6d. Si timeout → status='pending' (se reintenta)
```

---

## Procesamiento de Posts (Fase 1)

### Endpoint: `/process-posts`

**Propósito**: Crear jobs en Information Tracer API para posts pendientes de procesar.

### Flujo Detallado

#### 1. Consulta de Posts

```python
# Query posts con status='noreplies'
posts = query_posts_without_replies(max_posts=None)

# Priorización:
# - Twitter posts primero
# - Dentro de cada plataforma: ordenados por created_at (más antiguos primero)
# - Si max_posts especificado: prioriza Twitter completamente
```

**Validaciones**:
- ✅ Verifica que posts tengan `post_id`
- ✅ Aplica límite `max_posts` si se especifica

#### 2. Validación de Posts

Para cada post, se realizan las siguientes validaciones:

**2.1. Validación de Parámetros de Respuestas**

```python
replies_count = post.get("replies_count")
max_posts_replies = post.get("max_posts_replies") or post.get("max_replies")  # backward compat

# Determina max_posts_to_fetch:
# Prioridad: max_posts_replies > replies_count > default (100)
if max_posts_replies is not None and max_posts_replies > 0:
    max_posts_to_fetch = max_posts_replies
elif replies_count is not None and replies_count > 0:
    max_posts_to_fetch = replies_count
else:
    max_posts_to_fetch = 100  # Default
```

**2.2. Validación de Posts sin Respuestas Esperadas**

```python
# Skip si no se esperan respuestas
if (replies_count is None or replies_count <= 0) and \
   (max_posts_replies is None or max_posts_replies <= 0):
    update_post_status(doc_id, "skipped")
    # Log como skipped
    continue
```

**2.3. Validación de Existencia en GCS**

```python
# Verifica si ya existe JSON en GCS
info_data = read_from_gcs_if_exists(
    country, platform, candidate_id, post_id
)

if info_data is not None:
    # File ya existe, actualiza post a 'done' y skip
    update_post_status(doc_id, "done")
    continue
```

**2.4. Validación de Jobs Duplicados**

```python
# Previene creación de jobs duplicados
if has_existing_job_for_post(post_id):
    # Ya existe job pendiente/processing para este post
    continue
```

La función `has_existing_job_for_post()` verifica:
- ✅ Jobs con `status='pending'` para el mismo `post_id`
- ✅ Jobs con `status='processing'` para el mismo `post_id`

#### 3. Submit a Information Tracer

```python
job_id = submit_post_job(
    post_id=post_id,
    platform=platform,
    max_posts=max_posts_to_fetch,
    sort_by=sort_by  # 'time' o 'engagement'
)
```

**Query Format**:
- Para replies: `reply:{post_id}`
- `timeline_only=False` (keyword search)
- `sort_by` aplica solo a keyword search

**Validaciones en Submit**:
- ✅ Verifica HTTP status codes (429, 403, 400+)
- ✅ Verifica presencia de `id_hash256` en respuesta
- ✅ Detecta errores de quota/limit en mensajes

**Manejo de Errores**:
- Si submit falla → se detiene el procesamiento (probable quota/rate limit)
- Se registra error y se guarda en logs

#### 4. Guardado de Job

```python
if job_id:
    job_doc_id = save_pending_job(
        job_id=job_id,
        post_doc_id=doc_id,
        post_id=post_id,
        platform=platform,
        country=country,
        candidate_id=candidate_id,
        max_posts=max_posts_to_fetch,
        sort_by=sort_by,
    )
    # Actualiza post status a 'processing'
    update_post_status(post_doc_id, "processing")
```

**Campos del Job Document**:
- `job_id`: hash de Information Tracer
- `post_doc_id`: referencia al post en Firestore
- `post_id`: ID del post
- `platform`, `country`, `candidate_id`: metadata
- `max_posts`, `sort_by`: parámetros de búsqueda
- `status`: `"pending"` (inicial)
- `created_at`, `updated_at`: timestamps

#### 5. Logging

El sistema guarda logs de ejecución en GCS:
- Logs de éxito/fallo para cada post
- Logs de errores en archivo separado
- Metadatos: post_id, job_id, status_code, timestamps

---

## Procesamiento de Jobs (Fase 2)

### Endpoint: `/process-jobs`

**Propósito**: Verificar estado de jobs pendientes, obtener resultados y guardarlos en GCS.

### Flujo Detallado

#### 1. Verificación de Cuota (Pre-procesamiento)

**ANTES** de procesar cualquier job, se verifica la cuota de Information Tracer API:

```python
api_usage = check_api_usage(settings.information_tracer_api_key)
daily_usage = api_usage["usage"]["day"]
searches_used = daily_usage.get("searches_used", 0)
daily_limit = limits.get("max_searches_per_day", 0)

if daily_limit > 0 and searches_used >= daily_limit:
    # Cuota excedida (400/400)
    return results  # Early return sin procesar
```

**Razón**: Evita hacer llamadas API innecesarias cuando la cuota está agotada.

#### 2. Consulta de Jobs Pendientes

```python
jobs = query_pending_jobs(max_jobs=max_jobs)
# Ordenados por created_at (más antiguos primero)
```

#### 3. Procesamiento de Cada Job

Para cada job, se ejecuta el siguiente flujo:

**3.1. Validación de Campos Requeridos**

```python
if not job_id or not job_doc_id:
    # Error: campos requeridos faltantes
    results["failed"] += 1
    continue
```

**3.2. Actualización de Estado a "processing"**

```python
update_job_status(job_doc_id, "processing")
```

**3.3. Verificación de Estado en Information Tracer**

```python
status = check_status(job_id, settings.information_tracer_api_key)
```

**Estados posibles**:
- `"finished"`: Job completado exitosamente
- `"failed"`: Job falló
- `"timeout"`: Job no completó en tiempo máximo (80 rounds × 40s = ~53 minutos)

#### 4. Manejo de Estado "finished"

Si el job está `finished`:

**4.1. Obtención de Resultados**

```python
result = get_result(
    job_id,
    settings.information_tracer_api_key,
    platform.lower()
)
```

**Validaciones**:
- ✅ Verifica que `result is not None`
- ✅ Si `result is None` → verifica quota (puede ser `quota_exceeded`)
- ✅ Marca como `failed` o `quota_exceeded` según corresponda

**4.2. Validación de Resultado Vacío**

```python
if _is_result_empty(result):
    # Resultado vacío ([] o {})
    update_job_status(job_doc_id, "empty_result")
    # NO actualiza post a 'noreplies' (evita retry automático)
    continue
```

La función `_is_result_empty()` valida:
- ✅ `result is None` → vacío
- ✅ Lista vacía `[]` → vacío
- ✅ Diccionario vacío `{}` → vacío
- ✅ Diccionario con todos los valores vacíos → vacío

**4.3. Detección de Reintentos**

```python
# Verifica si es un retry
existing_file = read_from_gcs_if_exists(country, platform, candidate_id, post_id)
current_retry_count = job.get("retry_count", 0)

is_retry = existing_file is not None or current_retry_count > 0
```

**Tipos de reintentos**:
1. **Retry desde empty_result**: `retry_count > 0`
2. **Retry por archivo existente**: `existing_file is not None`

**4.4. Preparación de Metadata para Reintentos**

Si es un retry, se prepara metadata:

```python
if is_retry:
    retry_count = increment_job_retry_count(job_doc_id)
    metadata = {
        "is_retry": True,
        "retry_count": retry_count,
        "retry_timestamp": now.isoformat(),
        "previous_file_existed": existing_file is not None,
    }
    if existing_file:
        metadata["older_version"] = existing_file
```

**4.5. Guardado en GCS**

```python
gcs_uri = save_to_gcs(
    result,
    country,
    platform,
    candidate_id,
    post_id,
    metadata  # Incluye info de retry si aplica
)
```

**Validaciones en save_to_gcs()**:
- ✅ Verifica que `GCS_BUCKET_NAME` esté configurado
- ✅ Valida que `data` no esté vacío (`_is_result_empty()`)
- ✅ Estructura de path: `country/platform/candidate_id/{post_id}.json`
- ✅ Agrega metadata al JSON si es retry

**4.6. Actualización de Estados**

```python
# Actualiza post a 'done'
update_post_status(post_doc_id, "done")

# Actualiza job a 'done'
update_job_status(job_doc_id, "done")
```

#### 5. Manejo de Estado "failed"

Si el job está `failed`:

**5.1. Verificación de Cuota**

```python
# Verifica si la quota está excedida
api_usage = check_api_usage(settings.information_tracer_api_key)
searches_used = daily_usage.get("searches_used", 0)
daily_limit = limits.get("max_searches_per_day", 0)

if daily_limit > 0 and searches_used >= daily_limit:
    final_status = "quota_exceeded"
else:
    final_status = "failed"
```

**Diferencias**:
- `failed`: Fallo permanente (post eliminado, inválido, etc.)
- `quota_exceeded`: Fallo temporal por quota agotada

**5.2. Actualización de Estados**

```python
update_job_status(job_doc_id, final_status)

# Actualiza post a 'noreplies' solo si no hay otros jobs pendientes/processing
if post_doc_id and not has_existing_job_for_post(post_id):
    update_post_status(post_doc_id, "noreplies")
```

#### 6. Manejo de Estado "timeout"

```python
elif status == "timeout":
    # Job aún procesando, mantener como pending
    update_job_status(job_doc_id, "pending")
    results["still_pending"] += 1
```

El job se mantiene en `pending` para ser verificado en la próxima ejecución.

#### 7. Manejo de Excepciones

Si ocurre una excepción durante el procesamiento:

```python
except Exception as e:
    # Verifica quota en excepciones también
    if quota_exceeded:
        final_status = "quota_exceeded"
    else:
        final_status = "failed"
    
    update_job_status(job_doc_id, final_status)
    
    # Actualiza post a 'noreplies' si no hay otros jobs
    if not has_existing_job_for_post(post_id):
        update_post_status(post_doc_id, "noreplies")
```

---

## Validaciones

### Validaciones en Fase 1 (process-posts)

1. **Validación de Campos Requeridos**
   - ✅ `post_id` debe existir
   - ✅ `job_id`, `post_doc_id`, `post_id` requeridos para guardar job

2. **Validación de Parámetros de Respuestas**
   - ✅ Determina `max_posts_to_fetch` (max_posts_replies > replies_count > 100)
   - ✅ Valida si post debe ser skipped (sin respuestas esperadas)

3. **Validación de Duplicados**
   - ✅ Verifica si archivo ya existe en GCS
   - ✅ Verifica si ya existe job pendiente/processing para el post

4. **Validación de Submit**
   - ✅ HTTP status codes (429, 403, 400+)
   - ✅ Presencia de `id_hash256` en respuesta
   - ✅ Detección de errores de quota/limit

### Validaciones en Fase 2 (process-jobs)

1. **Validación Pre-procesamiento**
   - ✅ Cuota de API antes de procesar (early return si excedida)
   - ✅ Campos requeridos del job (`job_id`, `job_doc_id`)

2. **Validación de Resultados**
   - ✅ Resultado no es `None`
   - ✅ Resultado no está vacío (`_is_result_empty()`)
   - ✅ Verificación de cuota cuando resultado es `None`

3. **Validación de Guardado en GCS**
   - ✅ `GCS_BUCKET_NAME` configurado
   - ✅ Datos no vacíos antes de guardar
   - ✅ Estructura de path válida

4. **Validación de Estados**
   - ✅ Verificación de quota cuando job falla
   - ✅ Verificación de jobs existentes antes de actualizar post

### Validación de Resultados Vacíos

La función `_is_result_empty()` implementa validaciones exhaustivas:

```python
def _is_result_empty(result: dict[str, Any] | list[Any]) -> bool:
    # None → vacío
    if result is None:
        return True
    
    # Lista vacía → vacío
    if isinstance(result, list):
        return len(result) == 0
    
    # Diccionario vacío → vacío
    if isinstance(result, dict):
        if len(result) == 0:
            return True
        
        # Verifica si todos los valores están vacíos
        for value in result.values():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            if isinstance(value, (list, dict)) and len(value) == 0:
                continue
            # Si encuentra un valor no vacío, no está vacío
            return False
        
        return True  # Todos los valores estaban vacíos
    
    return False
```

---

## Mecanismos de Reintentos

### Tipos de Reintentos

El sistema implementa varios mecanismos de reintentos:

#### 1. Reintento Automático por Timeout

**Cuándo**: Cuando `check_status()` retorna `"timeout"`

**Acción**: El job se mantiene en `status='pending'` para ser verificado en la próxima ejecución de `/process-jobs`.

**Límite**: El sistema sigue intentando hasta que el job termine o falle (no hay límite de intentos para timeouts).

#### 2. Reintento Manual de Empty Result Jobs

**Cuándo**: Para jobs con `status='empty_result'`

**Endpoint**: `POST /empty-result-jobs/retry`

**Funcionamiento**:

```python
def retry_job_from_empty_result(doc_id: str) -> int:
    # Reutiliza el mismo job document (NO crea uno nuevo)
    # Actualiza: status='pending', incrementa retry_count
    # Si post está en 'done', lo actualiza a 'noreplies'
```

**Características**:
- ✅ Reutiliza el mismo documento de job (mismo `job_id`)
- ✅ Incrementa `retry_count` automáticamente
- ✅ Actualiza post a `noreplies` si está en `done`
- ✅ El job será procesado en la próxima ejecución de `/process-jobs`

**Filtros Disponibles**:
- `candidate_id`: Filtrar por candidato
- `platform`: Filtrar por plataforma
- `country`: Filtrar por país
- `limit`: Límite de jobs a reintentar

**Ejemplo de Uso**:
```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?limit=10&candidate_id=hnd09sosa"
```

#### 3. Reintento Automático por Fallo (con condiciones)

**Cuándo**: Cuando un job falla (`status='failed'`) Y NO hay otros jobs pendientes/processing para el mismo post

**Acción**: El post se actualiza a `status='noreplies'`, permitiendo que `/process-posts` cree un nuevo job.

**Limitación**: Solo funciona si NO hay otros jobs activos para el post (previene duplicados).

#### 4. Verificación de Archivo Existente en GCS (antes de procesar)

**Cuándo**: Antes de procesar un job (`status == 'finished'`), el sistema verifica si ya existe un JSON en GCS

**Comportamiento**:

1. **Si el JSON existe y tiene contenido válido (no vacío)**:
   - Se salta el procesamiento completamente
   - No se consulta Information Tracer (ahorra quota)
   - El job se marca como `done`
   - El post se actualiza a `done` si no lo estaba
   - Se logea como skipped con razón: "JSON file already exists in GCS with valid content"

2. **Si el JSON no existe o está vacío (None o [])**:
   - Se procesa normalmente
   - Se consulta Information Tracer para obtener resultados
   - Si el archivo existía pero estaba vacío, se detecta como retry:
     - `is_retry=True`
     - Se incrementa `retry_count`
     - Se guarda metadata con información del retry
     - `previous_file_existed: true` en metadata

**Propósito**: 
- Evitar reprocesar jobs innecesariamente cuando ya hay datos válidos en GCS
- Ahorrar quota de Information Tracer API
- Solo reprocesar cuando es necesario (archivo vacío o inexistente)

### Tracking de Reintentos

El sistema rastrea reintentos mediante:

1. **Campo `retry_count` en Job Document**
   - Se incrementa automáticamente en cada retry
   - Valor inicial: 0

2. **Metadata en JSON guardado en GCS**
   ```json
   {
     "_metadata": {
       "is_retry": true,
       "retry_count": 1,
       "retry_timestamp": "2026-01-10T12:00:00Z",
       "previous_file_existed": true,
       "older_version": "gs://bucket/path/file.json"
     },
     ...
   }
   ```

3. **Logs de Ejecución**
   - Incluyen `is_retry` y `retry_count` en logs de éxito
   - Identifican fácilmente jobs que fueron reintentados

### Limitaciones de Reintentos

1. **Jobs Failed NO tienen retry automático**
   - Los jobs con `status='failed'` NO se reintentan automáticamente
   - Requieren intervención manual si se desea reintentar
   - **Razón**: La mayoría son fallos permanentes (post eliminado, inválido, etc.)

2. **Empty Result Jobs NO se reintentan automáticamente**
   - Los jobs con `status='empty_result'` requieren uso manual del endpoint `/empty-result-jobs/retry`
   - **Razón**: Evita desperdiciar quota en posts que realmente no tienen respuestas

3. **Quota Exceeded NO se reintenta inmediatamente**
   - Jobs con `status='quota_exceeded'` esperan hasta el siguiente día (reset de quota)
   - Requieren intervención manual o esperar al reset diario

---

## Estados y Transiciones

### Estados de Posts

| Estado | Descripción | Cuándo se Asigna |
|--------|-------------|------------------|
| `noreplies` | Post pendiente de procesar | Estado inicial, o cuando job falla y no hay otros jobs activos |
| `processing` | Post en proceso | Cuando se crea un job para el post |
| `done` | Post procesado exitosamente | Cuando job se completa y resultados se guardan en GCS |
| `skipped` | Post saltado | Cuando `max_posts_replies <= 0` y `replies_count <= 0` |

### Transiciones de Posts

```
noreplies → processing  (cuando se crea un job)
processing → done       (job completado exitosamente)
processing → noreplies  (job falla y no hay otros jobs activos)
noreplies → skipped     (max_posts_replies <= 0 y replies_count <= 0)
```

### Estados de Jobs

| Estado | Descripción | Cuándo se Asigna |
|--------|-------------|------------------|
| `pending` | Job pendiente de verificar | Estado inicial, o cuando job tiene timeout/status desconocido |
| `processing` | Job en proceso de verificación | Cuando se inicia verificación del estado |
| `done` | Job completado exitosamente | Job finished, resultado no vacío, guardado en GCS |
| `failed` | Job falló permanentemente | Information Tracer reporta fallo Y quota NO excedida |
| `quota_exceeded` | Job falló por quota excedida | Information Tracer reporta fallo Y quota está excedida |
| `empty_result` | Job completado pero resultado vacío | Job finished pero resultado es [] o {} |
| `verified` | Job verificado como resultado vacío esperado | Empty result job verificado manualmente (twitter, replies_count <= 2) |

### Transiciones de Jobs

```
pending → processing → done           (job completado exitosamente)
pending → processing → failed         (job falló, quota disponible)
pending → processing → quota_exceeded (job falló, quota excedida)
pending → processing → empty_result   (job finished pero resultado vacío)
pending → processing → pending        (timeout o status desconocido, se reintenta)
empty_result → pending → done/failed  (retry manual desde empty_result)
```

### Diferencias entre Estados

**`failed` vs `quota_exceeded`**:
- `failed`: Fallo permanente (post eliminado, inválido, error de API)
- `quota_exceeded`: Fallo temporal por quota diaria agotada (se resuelve al día siguiente)

**`failed` vs `empty_result`**:
- `failed`: Job NO se completó (Information Tracer reporta fallo)
- `empty_result`: Job SÍ se completó (status="finished") pero resultado está vacío

**`empty_result` vs `verified`**:
- `empty_result`: Resultado vacío, pendiente de verificación
- `verified`: Resultado vacío confirmado como esperado (post tiene pocas respuestas)

---

## Manejo de Errores

### Estrategias de Manejo

1. **Early Returns**
   - Cuota excedida: retorna sin procesar
   - Submit falla: detiene procesamiento (probable quota/rate limit)

2. **Validaciones Defensivas**
   - Verifica campos requeridos antes de usar
   - Verifica configuración (API keys, bucket names)
   - Valida tipos de datos

3. **Try-Catch Granular**
   - Cada job se procesa en try-catch individual
   - Errores no detienen procesamiento de otros jobs
   - Se registran errores para análisis posterior

4. **Logging Exhaustivo**
   - Logs de ejecución guardados en GCS
   - Logs de errores en archivo separado
   - Metadatos completos (post_id, job_id, timestamps, etc.)

### Tipos de Errores

#### 1. Errores de Configuración

- `INFORMATION_TRACER_API_KEY` no configurado
- `GCS_BUCKET_NAME` no configurado
- Retornan error inmediatamente

#### 2. Errores de API

- **429 (Rate Limit)**: Se detecta, no se reintenta automáticamente
- **403 (Forbidden/Quota)**: Se detecta, se marca como `quota_exceeded`
- **400+ (Otros errores)**: Se detectan, se marcan como `failed`

#### 3. Errores de Validación

- Campos faltantes: se registran, se continúa con siguiente
- Resultados vacíos: se marcan como `empty_result` (NO es error técnico)
- Datos inválidos: se registran como errores

#### 4. Errores de Firestore/GCS

- Se capturan en try-catch
- Se registran pero no detienen procesamiento
- Operaciones críticas tienen manejo específico

### Recuperación de Errores

1. **Errores Temporales (Quota)**
   - Se marcan como `quota_exceeded`
   - Se resuelven automáticamente al día siguiente (reset de quota)
   - NO se reintentan hasta reset de quota

2. **Errores de Timeout**
   - Se mantienen en `pending`
   - Se reintentan en próxima ejecución de `/process-jobs`
   - Sin límite de intentos

3. **Errores Permanentes (Failed)**
   - Se marcan como `failed`
   - Post se actualiza a `noreplies` (si no hay otros jobs)
   - Requieren intervención manual para reintentar

4. **Errores de Resultado Vacío**
   - Se marcan como `empty_result`
   - Requieren verificación manual
   - Se pueden reintentar con `/empty-result-jobs/retry`

---

## Control de Cuotas

### Verificación de Cuota

El sistema verifica la cuota de Information Tracer API en múltiples puntos:

#### 1. Pre-procesamiento (process-jobs)

**Cuándo**: Antes de procesar cualquier job

**Implementación**:
```python
api_usage = check_api_usage(settings.information_tracer_api_key)
searches_used = daily_usage.get("searches_used", 0)
daily_limit = limits.get("max_searches_per_day", 0)

if searches_used >= daily_limit:
    # Early return, no procesa jobs
    return results
```

**Razón**: Evita hacer llamadas API innecesarias cuando quota está agotada.

#### 2. Durante Procesamiento (cuando job falla)

**Cuándo**: Cuando `check_status()` retorna `"failed"` o `get_result()` retorna `None`

**Implementación**:
```python
if status == "failed" or result is None:
    # Verifica quota
    if searches_used >= daily_limit:
        final_status = "quota_exceeded"
    else:
        final_status = "failed"
```

**Razón**: Diferencia entre fallos por quota y fallos permanentes.

#### 3. En Excepciones

**Cuándo**: Cuando ocurre una excepción durante procesamiento

**Implementación**: Similar a punto 2, verifica quota antes de marcar como `failed`.

### Límites de Cuota

- **Límite diario**: 400 searches/día
- **Reset**: Diario (según timezone de Information Tracer)
- **Detección**: `searches_used >= max_searches_per_day`

### Comportamiento con Cuota Excedida

1. **Pre-procesamiento**: Early return, no procesa jobs
2. **Durante procesamiento**: Marca jobs como `quota_exceeded`
3. **No hay retry automático**: Jobs esperan hasta reset de quota
4. **Post NO se actualiza a noreplies**: Evita crear nuevos jobs cuando quota está agotada

### Monitoreo de Cuota

El sistema registra eventos de quota en logs:
- Mensaje de advertencia cuando quota está excedida
- Logs incluyen `searches_used/daily_limit`
- Logs de ejecución incluyen eventos de quota

**Script de monitoreo**: `scripts/check_api_quota.py`

---

## Flujos de Datos

### Flujo Completo: Post Nuevo → Resultado en GCS

```
1. Post creado en Firestore
   status='noreplies'
   ↓
2. /process-posts ejecutado
   - Query posts (status='noreplies')
   - Submit a Information Tracer
   - job_id guardado en pending_jobs
   - Post status='processing'
   ↓
3. Information Tracer procesa job (asíncrono, 5-10 minutos)
   ↓
4. /process-jobs ejecutado (cada 30 minutos)
   - Query pending_jobs
   - **Verifica si existe JSON en GCS**
     - Si existe y NO está vacío → Skip processing, marca job/post como 'done'
     - Si no existe o está vacío → Continúa procesamiento
   - Check status → 'finished'
   - Get result → datos de respuestas
   - Save to GCS (raw/ layer)
   - Post status='done'
   - Job status='done'
   ↓
5. Resultado disponible en GCS
   gs://bucket/country/platform/candidate_id/{post_id}.json
```

### Flujo: Reintento desde Empty Result

```
1. Job tiene status='empty_result'
   ↓
2. /empty-result-jobs/retry ejecutado
   - Query empty_result jobs
   - Update job: status='pending', retry_count++
   - Si post='done': update post='noreplies'
   ↓
3. /process-jobs ejecutado
   - Detecta job en pending
   - Check status → 'finished'
   - Get result → datos (esta vez con resultados)
   - Detecta is_retry=True (retry_count > 0)
   - Save to GCS con metadata de retry
   - Post status='done'
   - Job status='done'
```

### Flujo: Fallo y Reintento Automático

```
1. Job tiene status='failed' (quota disponible)
   ↓
2. Post actualizado a 'noreplies' (si no hay otros jobs)
   ↓
3. /process-posts ejecutado
   - Detecta post='noreplies'
   - Submit nuevo job
   - Nuevo job_id en pending_jobs
   ↓
4. /process-jobs ejecutado
   - Procesa nuevo job
   - Si éxito → done
   - Si falla nuevamente → failed (sin más retry automático)
```

### Flujo: Cuota Excedida

```
1. /process-jobs ejecutado
   ↓
2. Verificación de cuota (pre-procesamiento)
   - searches_used >= daily_limit (400/400)
   - Early return, no procesa jobs
   ↓
3. Si job ya estaba procesándose cuando quota se excedió:
   - Job falla
   - Verificación de quota → quota_exceeded
   - Job status='quota_exceeded'
   - Post NO se actualiza a 'noreplies'
   ↓
4. Al día siguiente (reset de quota):
   - Jobs con quota_exceeded pueden reintentarse manualmente
   - O esperar a que /process-jobs los detecte si se actualizan a 'pending'
```

---

## Referencias

- [Estados de Firestore](./FIRESTORE_STATUS.md) - Documentación detallada de estados
- [Empty Result Jobs](./EMPTY_RESULT_JOBS.md) - Guía de uso de empty result jobs
- [Information Tracer](./INFORMATION_TRACER.md) - Documentación de la API
- [Testing Process Posts Local](./TESTING_PROCESS_POSTS_LOCAL.md) - Guía de testing
- [Failed Jobs Analysis](./FAILED_JOBS_ANALYSIS.md) - Análisis de jobs fallidos

