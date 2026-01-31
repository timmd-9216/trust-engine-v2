# Empty Result Jobs - Guía de Uso
curl -X POST "http://localhost:8082/empty-result-jobs/retry"
Esta guía explica cómo manejar jobs con status `empty_result` y los endpoints disponibles para consultar y retry estos jobs.

## ¿Qué son los Empty Result Jobs?

Los jobs con status `empty_result` son trabajos que se completaron exitosamente según Information Tracer (status="finished"), pero el resultado obtenido está vacío (lista vacía o diccionario vacío). Esto puede ocurrir cuando:

- El post no tiene respuestas reales
- Information Tracer no encontró resultados que coincidan con la query
- El resultado es una lista o diccionario vacío

Estos jobs se distinguen de los jobs `failed` porque técnicamente terminaron correctamente, pero no hay datos útiles.

### Logs vs Firestore: ¿por qué hay empty_result en logs pero 0 en la colección?

Los **logs de ejecución** (GCS, `error_type: "empty_result"`) registran **qué pasó en esa corrida**. El **Firestore** guarda el **estado actual** del job.

Si un job tuvo resultado vacío, se marca `empty_result` y se escribe en el log. Si más adelante ese job se **reintenta** (p. ej. con `POST /empty-result-jobs/retry`) y en el reintento Information Tracer devuelve datos, el job pasa a `done`. Por tanto:

- En **logs antiguos** seguirás viendo entradas `empty_result` para ese job.
- En **Firestore** ese job ya está en `done`, no en `empty_result`.

Es normal que la colección tenga 0 jobs con `empty_result` y los logs sigan mostrando muchos: son jobs que ya fueron reintentados y pasaron a `done`.

## Endpoints Disponibles

### 1. GET `/jobs/count` ⭐ Genérico (Recomendado)

Cuenta jobs con cualquier status en Firestore con filtros opcionales.

**Método:** `GET`

**Parámetros de query:**
- `status`: Job status a contar. Por defecto: `pending`. Valores válidos: `pending`, `empty_result`, `done`, `failed`, `processing`, `verified`
- `failed_without_done`: Solo aplica si `status=failed`. Si `true`, cuenta únicamente jobs en `failed` que **no** tienen otro job en `done` para el mismo `post_id` (candidatos a reintentar). Sin este parámetro, se cuentan todos los jobs en `failed`.
- `candidate_id`: Opcional - Filtrar por candidate_id
- `platform`: Opcional - Filtrar por platform (e.g., 'twitter', 'instagram')
- `country`: Opcional - Filtrar por country

**Respuesta:**
```json
{
  "count": 150,
  "status": "pending",
  "filters": {
    "candidate_id": null,
    "platform": null,
    "country": null
  }
}
```

**Ejemplos de uso:**

```bash
# Contar jobs pendientes (por defecto)
curl -X GET "http://localhost:8082/jobs/count"

# Contar jobs pendientes con filtro
curl -X GET "http://localhost:8082/jobs/count?status=pending&candidate_id=hnd09sosa"

# Contar jobs con empty_result
curl -X GET "http://localhost:8082/jobs/count?status=empty_result"

# Contar jobs done
curl -X GET "http://localhost:8082/jobs/count?status=done"

# Contar todos los jobs failed
curl -X GET "http://localhost:8082/jobs/count?status=failed"

# Contar solo jobs failed SIN otro job en done para el mismo post_id (candidatos a reintentar)
curl -X GET "http://localhost:8082/jobs/count?status=failed&failed_without_done=true"

# Contar con múltiples filtros
curl -X GET "http://localhost:8082/jobs/count?status=pending&candidate_id=hnd09sosa&platform=twitter"
```

### 2. GET `/empty-result-jobs/count` (Compatibilidad)

Cuenta jobs con status `empty_result` en Firestore con filtros opcionales.

**Método:** `GET`

**Parámetros de query (opcionales):**
- `candidate_id`: Filtrar por candidate_id
- `platform`: Filtrar por platform (e.g., 'twitter', 'instagram')
- `country`: Filtrar por country

**Respuesta:**
```json
{
  "count": 498,
  "filters": {
    "candidate_id": null,
    "platform": null,
    "country": null
  }
}
```

**Ejemplos de uso:**

```bash
# Contar todos los jobs con empty_result
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count"

# Contar con filtro por candidate
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count?candidate_id=hnd09sosa"

# Contar con filtro por platform
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count?platform=twitter"

# Contar con múltiples filtros
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count?candidate_id=hnd09sosa&platform=twitter&country=honduras"
```

**Uso con gcloud:**

```bash
# Contar todos
gcloud run services proxy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --port=8080

curl http://localhost:8080/empty-result-jobs/count
```

### 3. POST `/empty-result-jobs/retry`

Retry jobs con status `empty_result` moviéndolos a `pending` para reprocesarlos.

**Método:** `POST`

**Parámetros de query (opcionales):**
- `candidate_id`: Filtrar por candidate_id
- `platform`: Filtrar por platform (e.g., 'twitter', 'instagram')
- `country`: Filtrar por country
- `limit`: Máximo número de jobs a retry. Si es None, retry todos los jobs que coincidan con los filtros.

**Respuesta:**
```json
{
  "total_found": 10,
  "retried": 10,
  "errors": [],
  "retried_jobs": [
    {
      "doc_id": "abc123",
      "job_id": "2389af87514ee2c735bbdbf1ea9358a264e139e8e6e5850ac132e31e43050bf4",
      "post_id": "1995703727769199092",
      "platform": "twitter",
      "country": "honduras",
      "candidate_id": "hnd09sosa",
      "previous_retry_count": 0,
      "new_retry_count": 1
    }
  ]
}
```

**Ejemplos de uso:**

```bash
# Retry todos los jobs con empty_result
curl -X POST "https://scrapping-tools-xxx.run.app/empty-result-jobs/retry"

# Retry con límite
curl -X POST "https://scrapping-tools-xxx.run.app/empty-result-jobs/retry?limit=10"

# Retry para un candidate específico
curl -X POST "https://scrapping-tools-xxx.run.app/empty-result-jobs/retry?candidate_id=hnd09sosa"

# Retry con múltiples filtros
curl -X POST "https://scrapping-tools-xxx.run.app/empty-result-jobs/retry?candidate_id=hnd09sosa&platform=twitter&limit=5"
```

**Uso con gcloud:**

```bash
# Retry 10 jobs
gcloud run services proxy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --port=8080

curl -X POST "http://localhost:8080/empty-result-jobs/retry?limit=10"
```

## ¿Qué hace el retry?

Cuando se retry un job con `empty_result`:

1. **Reutiliza el mismo job document**: NO se crea un nuevo job. El mismo documento de Firestore se actualiza:
   - El `job_id` (hash de Information Tracer) se mantiene igual
   - El `post_doc_id` (referencia al post) se mantiene igual
   - Solo se actualizan: `status`, `retry_count`, y `updated_at`

2. **Cambia el status** del job de `empty_result` a `pending`

3. **Incrementa `retry_count`** automáticamente

4. **Actualiza el post asociado**: Si el post está en status `done`, se actualiza a `noreplies` para permitir reprocesamiento

5. **El job será procesado** en la próxima ejecución de `/process-jobs`

6. **Los logs mostrarán** que es un reintento con `is_retry: true` y `retry_count: N`

### ¿Qué pasa con el job viejo?

**El job viejo NO se elimina ni se crea uno nuevo.** El mismo documento se reutiliza:

- **Mismo `job_id`**: El hash de Information Tracer se mantiene (es el mismo job en Information Tracer)
- **Misma referencia al post**: El `post_doc_id` se mantiene, manteniendo la relación entre job y post
- **Historial preservado**: El `retry_count` se incrementa, permitiendo rastrear cuántas veces se ha intentado

Esto es más eficiente que crear jobs nuevos porque:
- No duplica documentos en Firestore
- Mantiene el historial de reintentos en un solo lugar
- Information Tracer puede reutilizar el mismo job_id si es necesario

## Flujo de Trabajo Recomendado

### 1. Consultar cuántos jobs hay con empty_result

```bash
# Ver el total
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count"

# Ver por candidate
curl -X GET "https://scrapping-tools-xxx.run.app/empty-result-jobs/count?candidate_id=hnd09sosa"
```

### 2. Retry jobs (empezar con un límite pequeño para probar)

```bash
# Retry 5 jobs primero para verificar que funciona
curl -X POST "https://scrapping-tools-xxx.run.app/empty-result-jobs/retry?limit=5"
```

### 3. Procesar los jobs retry

Los jobs ahora tienen status `pending` y serán procesados automáticamente por el scheduler que ejecuta `/process-jobs` cada 30 minutos, o puedes ejecutarlo manualmente:

```bash
curl -X POST "https://scrapping-tools-xxx.run.app/process-jobs"
```

### 4. Verificar los logs

Cuando los jobs se procesen, los logs incluirán información de reintento:

```json
{
  "post_id": "1995703727769199092",
  "success": true,
  "is_retry": true,
  "retry_count": 1,
  "job_id": "2389af87514ee2c735bbdbf1ea9358a264e139e8e6e5850ac132e31e43050bf4"
}
```

## Script de Línea de Comandos

También puedes usar el script `scripts/retry_empty_result_jobs.py` para retry jobs desde la línea de comandos:

```bash
# Ver qué se retry (dry-run)
poetry run python scripts/retry_empty_result_jobs.py --dry-run --limit 5

# Retry jobs
poetry run python scripts/retry_empty_result_jobs.py --limit 10

# Retry con filtros
poetry run python scripts/retry_empty_result_jobs.py \
  --candidate-id hnd09sosa \
  --limit 5
```

## Notas Importantes

1. **Retry automático**: Los jobs retry se procesarán automáticamente en la próxima ejecución de `/process-jobs` (cada 30 minutos por el scheduler).

2. **Tracking de reintentos**: El campo `retry_count` se incrementa automáticamente, permitiendo rastrear cuántas veces se ha intentado reprocesar un job.

3. **Logs**: Los logs finales incluirán `is_retry: true` y `retry_count` para identificar fácilmente los reintentos.

4. **Filtros**: Puedes usar filtros para retry jobs específicos (por candidate, platform, country) en lugar de retry todos.

5. **Límites**: Es recomendable usar `limit` cuando retry muchos jobs para evitar sobrecargar el sistema.

## Relación con otros Endpoints

- **`/process-jobs`**: Procesa los jobs que fueron retry (ahora con status `pending`)
- **`/fix-jobs`**: Corrige jobs marcados como 'done' pero con JSONs vacíos en GCS (diferente de `empty_result`)
- **`/pending-jobs`**: Lista jobs pendientes (incluye los que fueron retry)

## Ver también

- [FIRESTORE_STATUS.md](../FIRESTORE_STATUS.md) - Documentación sobre estados de jobs y posts
- [INFORMATION_TRACER.md](../INFORMATION_TRACER.md) - Documentación sobre Information Tracer API

