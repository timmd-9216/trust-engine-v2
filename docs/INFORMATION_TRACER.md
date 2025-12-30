# Information Tracer - Guía de Integración

Esta guía explica cómo funciona Information Tracer, su API, y cómo lo integramos en nuestro sistema para recolectar datos de redes sociales.

## ¿Qué es Information Tracer?

Information Tracer es un servicio externo que permite recolectar datos de diversas redes sociales (Twitter, Instagram, Facebook, Reddit, YouTube, Threads, etc.) a través de una API REST.

**URL Base:** `https://informationtracer.com`

## Arquitectura Asíncrona

Information Tracer utiliza un modelo **asíncrono** basado en jobs (trabajos). Esto significa que:

1. **Submit**: Envías una solicitud de recolección y recibes un ID de job inmediatamente
2. **Check Status**: Puedes consultar el estado del job cuando quieras usando el ID
3. **Get Result**: Cuando el job está terminado, puedes obtener los resultados

Esta arquitectura permite procesar múltiples trabajos sin bloquear el sistema esperando resultados.

## Endpoints de la API

### 1. Submit (Crear Job)

**Endpoint:** `POST https://informationtracer.com/submit`

**Propósito:** Envía una solicitud para recolectar datos. Retorna un `id_hash256` (job ID) inmediatamente.

**Request Body:**
```json
{
  "query": "reply:1234567890",
  "token": "tu-api-key",
  "max_post": 100,
  "sort_by": "time",
  "start_date": "2020-01-01",
  "end_date": "2025-12-31",
  "platform_to_collect": ["twitter"],
  "timeline_only": false,
  "enable_ai": false
}
```

**Response:**
```json
{
  "id_hash256": "abc123def456..."
}
```

**Características:**
- ✅ **Responde inmediatamente** (no espera a que termine el trabajo)
- ✅ Retorna un `id_hash256` único para el job
- ✅ Information Tracer procesa el trabajo en segundo plano
- ⏱️ El procesamiento puede tardar desde segundos hasta varios minutos

**Parámetros importantes:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `query` | string | Formato depende del tipo de búsqueda:<br>- `"username"` - Búsqueda de cuenta<br>- `"from:@username"` - Búsqueda por keyword<br>- `"reply:post_id"` - Obtener respuestas de un post |
| `platform_to_collect` | array | Plataforma(s) a recolectar: `["twitter"]`, `["instagram"]`, etc. |
| `max_post` | int | Máximo de posts a recolectar (límites por plataforma) |
| `timeline_only` | bool | `true` = búsqueda de cuenta (incluye retweets)<br>`false` = búsqueda por keyword (excluye retweets) |

**Límites por plataforma:**

| Plataforma | Límite máximo |
|------------|---------------|
| Twitter | 10,000 |
| Facebook | 100 |
| Instagram | 100 |
| Reddit | 500 |
| YouTube | 500 |
| Threads | 200 |

### 2. Check Status (Consultar Estado)

**Endpoint:** `GET https://informationtracer.com/status?id_hash256={job_id}&token={token}`

**Propósito:** Consulta el estado de un job usando su `id_hash256`. Puedes consultarlo tantas veces como quieras.

**Response:**
```json
{
  "status": "finished",
  "tweet_preview": {...}
}
```

**Estados posibles:**

| Estado | Descripción |
|--------|-------------|
| `pending` | Job en cola, esperando ser procesado |
| `processing` | Job siendo procesado actualmente |
| `finished` | Job completado exitosamente, resultados disponibles |
| `failed` | Job falló durante el procesamiento |

**Características:**
- ✅ Puedes consultar el estado **en cualquier momento**
- ✅ Puedes hacer polling múltiples veces con el mismo `id_hash256`
- ✅ Los resultados están disponibles una vez que el estado es `finished`
- ⏱️ El procesamiento típicamente tarda de 1 a 5 minutos (puede variar)

**Ejemplo de polling:**

```python
# Consultar estado cada 40 segundos hasta que esté finished
while status != "finished":
    response = requests.get(f"{STATUS_URL}?id_hash256={job_id}&token={token}")
    status = response.json()["status"]
    if status != "finished":
        time.sleep(40)  # Esperar 40 segundos antes del próximo check
```

### 3. Get Result (Obtener Resultados)

**Endpoint:** `GET https://informationtracer.com/rawdata?token={token}&id={job_id}&source={platform}`

**Propósito:** Obtiene los resultados completos de un job que ya terminó (`status = "finished"`).

**Response:**
```json
[
  {
    "id": "1234567890",
    "text": "Contenido del post...",
    "created_at": "2025-01-15T10:30:00Z",
    "author": {...},
    ...
  },
  ...
]
```

**Características:**
- ✅ Solo funciona cuando `status = "finished"`
- ✅ Retorna un array con todos los posts/respuestas recolectados
- ✅ Los resultados están disponibles indefinidamente (mientras tengas el `job_id`)
- ⚠️ Si consultas antes de que termine, puede retornar error o datos parciales

## Flujo Completo

```
┌─────────────────────────────────────────────────────────────┐
│ 1. SUBMIT (POST /submit)                                    │
│    - Envías parámetros de búsqueda                          │
│    - Retorna: id_hash256 (job ID) ← INMEDIATO               │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ Information Tracer procesa en background
                        │ (puede tardar de segundos a minutos)
                        │
┌───────────────────────▼─────────────────────────────────────┐
│ 2. CHECK STATUS (GET /status?id_hash256=xxx)                │
│    - Puedes consultar cuando quieras                        │
│    - Retorna: "pending" | "processing" | "finished" | ...   │
│    - Puedes hacer polling múltiples veces                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        │ Cuando status = "finished"
                        │
┌───────────────────────▼─────────────────────────────────────┐
│ 3. GET RESULT (GET /rawdata?id=xxx&source=platform)         │
│    - Solo funciona cuando status = "finished"               │
│    - Retorna: Array con todos los datos recolectados        │
└─────────────────────────────────────────────────────────────┘
```

## Tipos de Búsquedas

### 1. Búsqueda de Cuenta (Account Search)

Obtiene todos los posts de una cuenta específica (incluyendo retweets).

**Query:** `"username"` (sin prefijo)
**timeline_only:** `true`
**Ejemplo:**
```python
submit(
    token=token,
    query="whitehouse",
    platform="twitter",
    timeline_only=True,
    ...
)
```

### 2. Búsqueda por Keyword

Busca posts que coincidan con una keyword (excluye retweets).

**Query:** `"from:@username"` o cualquier keyword
**timeline_only:** `false`
**Ejemplo:**
```python
submit(
    token=token,
    query="from:@whitehouse",
    platform="twitter",
    timeline_only=False,
    ...
)
```

### 3. Obtener Respuestas de un Post

Obtiene todas las respuestas/replies de un post específico.

**Query:** `"reply:post_id"`
**timeline_only:** `false` (siempre debe ser false para replies)
**Ejemplo:**
```python
submit(
    token=token,
    query="reply:2000043080984998363",
    platform="twitter",
    timeline_only=False,
    ...
)
```

## Cómo lo Usamos en Nuestro Sistema

Nuestro sistema implementa un flujo optimizado de dos fases para evitar bloquear esperando resultados:

### Fase 1: Crear Jobs (`/process-posts`)

1. Consulta posts con `status='noreplies'` en Firestore
   - **Prioridad por plataforma**: Los posts de Twitter se procesan primero
   - **Ordenamiento**: Dentro de cada plataforma, se ordenan por `created_at` (más antiguos primero)
   - Si se especifica `max_posts`, se priorizan los posts de Twitter (ej: si `max_posts=30` y hay 30+ posts de Twitter, todos serán de Twitter)
2. Para cada post, hace **submit** a Information Tracer
3. Guarda el `id_hash256` (job_id) en la colección `pending_jobs` de Firestore
4. **No espera** por los resultados (rápido, no bloquea)

**Código relevante:**
```python
# Submit el job
job_id = submit_post_job(post_id, platform, max_posts, sort_by)

# Guardar en Firestore
save_pending_job(
    job_id=job_id,
    post_doc_id=doc_id,
    post_id=post_id,
    ...
)
```

### Fase 2: Procesar Jobs (`/process-jobs`)

1. Consulta jobs con `status='pending'` en la colección `pending_jobs`
2. Para cada job, hace **check_status** con Information Tracer
3. Si el status es `finished`, hace **get_result**
4. Guarda los resultados en GCS
5. Actualiza el status del post a `done` en Firestore

**Código relevante:**
```python
# Check status
status = check_status(job_id, token)

if status == "finished":
    # Get results
    result = get_result(job_id, token, platform)
    
    # Save to GCS
    save_to_gcs(result, country, platform, candidate_id, post_id)
    
    # Update post status
    update_post_status(post_doc_id, "done")
```

## Ventajas de Este Enfoque

### ✅ Submit Rápido
- Los submits son inmediatos (no esperan resultados)
- Puedes procesar muchos posts rápidamente
- No bloquea el sistema

### ✅ Procesamiento Asíncrono
- Los jobs se procesan en segundo plano en Information Tracer
- Puedes consultar el estado cuando quieras
- Los resultados están disponibles cuando terminen

### ✅ Resiliencia
- Si un job falla, puedes reintentarlo
- Los jobs pendientes se pueden procesar después
- No pierdes trabajos si el sistema se reinicia

### ✅ Escalabilidad
- Puedes hacer muchos submits sin esperar
- Los resultados se procesan cuando están listos
- Distribuye la carga en el tiempo

## Configuración

### Variables de Entorno

```bash
# API Key de Information Tracer
INFORMATION_TRACER_API_KEY=tu-api-key-aqui
```

### Autenticación

Todos los endpoints requieren el `token` (API key) como parámetro:
- **Submit**: En el body del POST
- **Status**: Como query parameter `?token=xxx`
- **Rawdata**: Como query parameter `?token=xxx`

## Ejemplo de Uso Completo

```python
from trust_api.scrapping_tools.information_tracer import submit, check_status, get_result

# 1. Submit un job
job_id, params = submit(
    token="tu-api-key",
    query="reply:1234567890",
    max_post=100,
    sort_by="time",
    start_date="2020-01-01",
    end_date="2025-12-31",
    platform="twitter",
    timeline_only=False,
    enable_ai=False,
)

print(f"Job ID: {job_id}")

# 2. Consultar estado (puedes hacerlo cuando quieras)
status = check_status(job_id, "tu-api-key")
print(f"Status: {status}")

# 3. Cuando status = "finished", obtener resultados
if status == "finished":
    results = get_result(job_id, "tu-api-key", "twitter")
    print(f"Recolectados {len(results)} posts")
```

## Límites y Consideraciones

### Rate Limiting

Information Tracer tiene límites de uso basados en tu plan/subscription. Consulta tu uso con:

```python
from trust_api.scrapping_tools.information_tracer import check_api_usage

usage = check_api_usage(token="tu-api-key")
print(usage)
```

### Timeouts

- **Submit**: Timeout de 25 segundos (debería responder inmediatamente)
- **Status**: Timeout de 10 segundos
- **Rawdata**: Sin timeout específico (pero puede tardar si hay muchos datos)

### Tiempos de Procesamiento

Los tiempos típicos de procesamiento varían:

| Tipo de Búsqueda | Tiempo Típico |
|------------------|---------------|
| Respuestas de un post | 1-3 minutos |
| Búsqueda de cuenta pequeña | 2-5 minutos |
| Búsqueda de cuenta grande | 5-10+ minutos |

**Nota:** Estos tiempos son aproximados y pueden variar según la carga del servicio y la cantidad de datos.

## Troubleshooting

### Error: "Submission failed!"

- Verifica que tu API key sea válida
- Verifica que los parámetros sean correctos (especialmente `query` y `platform`)
- Verifica que no hayas excedido tu límite de uso

### Error: Status siempre "pending"

- Los jobs pueden tardar varios minutos en procesarse
- Espera más tiempo antes de consultar nuevamente
- Verifica que el job_id sea correcto

### Error: "Failed to retrieve results"

- Asegúrate de que el status sea `"finished"` antes de obtener resultados
- Verifica que el `platform` en `get_result` coincida con el usado en `submit`
- Verifica que tu API key sea válida

### Jobs que nunca terminan

- Si un job tarda mucho (más de 10-15 minutos), puede haber un problema
- Puedes intentar hacer un nuevo submit
- Contacta con Information Tracer si persiste el problema

## Referencias

- **Servicio:** https://informationtracer.com
- **Documentación de la API:** (consultar con Information Tracer para documentación oficial completa)

## Ver También

- [Testing Process Posts Locally](./TESTING_PROCESS_POSTS_LOCAL.md) - Cómo probar el flujo completo localmente
- [Configure Scheduler](./GCP/CONFIGURE_SCHEDULER.md) - Cómo configurar Cloud Scheduler para ejecutar automáticamente
- [Firestore Admin](./GCP/FIRESTORE_ADMIN.md) - Administración de Firestore y colección `pending_jobs`

