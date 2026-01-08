# Ejemplos de Uso - Empty Result Jobs Endpoints

Ejemplos prácticos de cómo usar los endpoints de empty_result jobs con curl en localhost.

## Configuración Inicial

### Opción 1: Servicio corriendo localmente

Si el servicio está corriendo localmente (por ejemplo, con `uvicorn`):

```bash
# El servicio debería estar en http://localhost:8082 (o el puerto que configuraste)
BASE_URL="http://localhost:8082"
```

### Opción 2: Proxy con gcloud (Cloud Run)

Si necesitas hacer proxy del servicio de Cloud Run a localhost:

```bash
# En una terminal, ejecuta el proxy
gcloud run services proxy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --port=8080

# En otra terminal, usa:
BASE_URL="http://localhost:8080"
```

## Endpoint 1: GET `/jobs/count` (Genérico - Recomendado)

### Contar jobs pendientes (por defecto)

```bash
curl -X GET "http://localhost:8082/jobs/count"
```

**Respuesta esperada:**
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

### Contar jobs pendientes con filtro

```bash
curl -X GET "http://localhost:8082/jobs/count?status=pending&candidate_id=hnd09sosa"
```

### Contar jobs con empty_result

```bash
curl -X GET "http://localhost:8082/jobs/count?status=empty_result"
```

### Contar jobs done

```bash
curl -X GET "http://localhost:8082/jobs/count?status=done"
```

### Contar jobs failed

```bash
curl -X GET "http://localhost:8082/jobs/count?status=failed"
```

## Endpoint 2: GET `/empty-result-jobs/count` (Compatibilidad)

### Contar todos los jobs con empty_result

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count"
```

**Respuesta esperada:**
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

### Contar con filtro por candidate_id

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count?candidate_id=hnd09sosa"
```

**Respuesta esperada:**
```json
{
  "count": 235,
  "filters": {
    "candidate_id": "hnd09sosa",
    "platform": null,
    "country": null
  }
}
```

### Contar con filtro por platform

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count?platform=twitter"
```

**Respuesta esperada:**
```json
{
  "count": 498,
  "filters": {
    "candidate_id": null,
    "platform": "twitter",
    "country": null
  }
}
```

### Contar con filtro por country

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count?country=honduras"
```

**Respuesta esperada:**
```json
{
  "count": 450,
  "filters": {
    "candidate_id": null,
    "platform": null,
    "country": "honduras"
  }
}
```

### Contar con múltiples filtros

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count?candidate_id=hnd09sosa&platform=twitter&country=honduras"
```

**Respuesta esperada:**
```json
{
  "count": 200,
  "filters": {
    "candidate_id": "hnd09sosa",
    "platform": "twitter",
    "country": "honduras"
  }
}
```

### Con formato bonito (usando jq)

```bash
curl -X GET "http://localhost:8082/empty-result-jobs/count" | jq
```

## Endpoint 3: POST `/empty-result-jobs/retry`

### Retry todos los jobs con empty_result (⚠️ Cuidado: puede ser muchos)

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry"
```

**Respuesta esperada:**
```json
{
  "total_found": 498,
  "retried": 498,
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
    },
    ...
  ]
}
```

### Retry con límite (recomendado para empezar)

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?limit=5"
```

**Respuesta esperada:**
```json
{
  "total_found": 5,
  "retried": 5,
  "errors": [],
  "retried_jobs": [
    {
      "doc_id": "abc123",
      "job_id": "...",
      "post_id": "...",
      "platform": "twitter",
      "country": "honduras",
      "candidate_id": "hnd09sosa",
      "previous_retry_count": 0,
      "new_retry_count": 1
    },
    ...
  ]
}
```

### Retry con filtro por candidate_id

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?candidate_id=hnd09sosa"
```

### Retry con filtro por candidate_id y límite

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?candidate_id=hnd09sosa&limit=10"
```

### Retry con filtro por platform

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?platform=twitter&limit=20"
```

### Retry con múltiples filtros

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?candidate_id=hnd09sosa&platform=twitter&country=honduras&limit=5"
```

### Con formato bonito (usando jq)

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?limit=5" | jq
```

### Ver solo el resumen (usando jq)

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?limit=5" | jq '{total_found, retried, errors: (.errors | length)}'
```

**Respuesta:**
```json
{
  "total_found": 5,
  "retried": 5,
  "errors": 0
}
```

## Flujo de Trabajo Completo

### 1. Verificar cuántos jobs hay

```bash
# Ver jobs pendientes (por defecto)
curl -X GET "http://localhost:8082/jobs/count" | jq '.count'

# Ver jobs pendientes por candidate
curl -X GET "http://localhost:8082/jobs/count?status=pending&candidate_id=hnd09sosa" | jq '.count'

# Ver jobs con empty_result
curl -X GET "http://localhost:8082/jobs/count?status=empty_result" | jq '.count'

# Ver jobs done
curl -X GET "http://localhost:8082/jobs/count?status=done" | jq '.count'
```

### 2. Retry un pequeño lote para probar

```bash
curl -X POST "http://localhost:8082/empty-result-jobs/retry?limit=5" | jq
```

### 3. Verificar que se retry correctamente

```bash
# Los jobs ahora deberían estar en pending
curl -X GET "http://localhost:8082/pending-jobs?max_jobs=10" | jq
```

### 4. Procesar los jobs retry

```bash
# Los jobs se procesarán automáticamente por el scheduler,
# o puedes procesarlos manualmente:
curl -X POST "http://localhost:8082/process-jobs"
```

## Ejemplos con Variables de Entorno

Para facilitar el uso, puedes definir variables:

```bash
# Definir la URL base
export BASE_URL="http://localhost:8082"

# O si usas proxy de gcloud:
export BASE_URL="http://localhost:8080"

# Contar
curl -X GET "${BASE_URL}/empty-result-jobs/count"

# Retry con límite
curl -X POST "${BASE_URL}/empty-result-jobs/retry?limit=10"

# Retry con filtros
curl -X POST "${BASE_URL}/empty-result-jobs/retry?candidate_id=hnd09sosa&limit=5"
```

## Script de Ejemplo Completo

```bash
#!/bin/bash

BASE_URL="${BASE_URL:-http://localhost:8082}"
CANDIDATE_ID="${1:-hnd09sosa}"
LIMIT="${2:-5}"

echo "=== Contando empty_result jobs para ${CANDIDATE_ID} ==="
COUNT=$(curl -s -X GET "${BASE_URL}/empty-result-jobs/count?candidate_id=${CANDIDATE_ID}" | jq -r '.count')
echo "Total: ${COUNT} jobs"

if [ "${COUNT}" -gt 0 ]; then
  echo ""
  echo "=== Retry ${LIMIT} jobs ==="
  curl -X POST "${BASE_URL}/empty-result-jobs/retry?candidate_id=${CANDIDATE_ID}&limit=${LIMIT}" | jq
  
  echo ""
  echo "=== Jobs retry. Ahora procesa con /process-jobs ==="
else
  echo "No hay jobs para retry"
fi
```

**Uso del script:**
```bash
# Usar valores por defecto (hnd09sosa, limit=5)
./retry_empty_jobs.sh

# Especificar candidate y limit
./retry_empty_jobs.sh hnd14espi 10
```

## Troubleshooting

### Error: Connection refused

```bash
# Verificar que el servicio está corriendo
curl http://localhost:8082/health

# O si usas proxy:
curl http://localhost:8080/health
```

### Error: 401 Unauthorized

Si usas proxy de gcloud, asegúrate de estar autenticado:

```bash
gcloud auth login
gcloud auth application-default login
```

### Ver logs del servicio

Si el servicio está corriendo localmente, los logs aparecerán en la terminal donde lo ejecutaste.

### Verificar que los jobs se retry correctamente

```bash
# Ver jobs pendientes (deberían incluir los retry)
curl -X GET "http://localhost:8082/pending-jobs?max_jobs=10" | jq '.jobs[] | select(.retry_count > 0)'
```

## Notas

- **Puerto local**: El servicio está corriendo en `http://localhost:8082`
- **Proxy gcloud**: Si usas proxy, el puerto por defecto es `8080` (puedes cambiarlo con `--port`)
- **jq**: Instala `jq` para formatear JSON: `brew install jq` (macOS) o `apt-get install jq` (Linux)
- **Límites**: Siempre usa `limit` cuando retry muchos jobs para evitar sobrecargar el sistema

