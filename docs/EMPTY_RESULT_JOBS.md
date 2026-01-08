# Empty Result Jobs - Guía de Uso

Esta guía explica cómo manejar jobs con status `empty_result` y los endpoints disponibles para consultar y retry estos jobs.

## ¿Qué son los Empty Result Jobs?

Los jobs con status `empty_result` son trabajos que se completaron exitosamente según Information Tracer (status="finished"), pero el resultado obtenido está vacío (lista vacía o diccionario vacío). Esto puede ocurrir cuando:

- El post no tiene respuestas reales
- Information Tracer no encontró resultados que coincidan con la query
- El resultado es una lista o diccionario vacío

Estos jobs se distinguen de los jobs `failed` porque técnicamente terminaron correctamente, pero no hay datos útiles.

## Endpoints Disponibles

### 1. GET `/empty-result-jobs/count`

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

### 2. POST `/empty-result-jobs/retry`

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

1. **Cambia el status** de `empty_result` a `pending`
2. **Incrementa `retry_count`** automáticamente
3. **El job será procesado** en la próxima ejecución de `/process-jobs`
4. **Los logs mostrarán** que es un reintento con `is_retry: true` y `retry_count: N`

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

