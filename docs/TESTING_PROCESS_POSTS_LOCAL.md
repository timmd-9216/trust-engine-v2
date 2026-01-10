# Testing Process Posts Locally - Guía Paso a Paso

Esta guía explica cómo probar localmente el flujo completo de procesamiento de posts:
1. **Crear jobs** (submit posts y guardar hash_id en `pending_jobs`)
2. **Procesar jobs** (después de esperar, buscar los resultados)
3. **Convertir a Parquet** (transformar JSONs a formato Parquet para analytics)

**Ver también:** 
- [Information Tracer - Guía de Integración](./INFORMATION_TRACER.md) para entender cómo funciona Information Tracer y su API.
- [JSON to Parquet Optimizations](./JSON_TO_PARQUET_OPTIMIZATIONS.md) para entender las optimizaciones del endpoint `/json-to-parquet`.

## Flujo del Sistema

El sistema funciona en tres fases separadas:

### Fase 1: Crear Jobs (`/process-posts`)
- Consulta posts con `status='noreplies'` en Firestore
- Para cada post, hace submit a Information Tracer API
- Guarda el `hash_id` (job_id) en la colección `pending_jobs` de Firestore
- Actualiza el status del post a `processing` en Firestore
- **No espera** por los resultados

### Fase 2: Procesar Jobs (`/process-jobs`)
- Consulta jobs con `status='pending'` en la colección `pending_jobs`
- **Verifica quota de Information Tracer API** antes de procesar (si quota excedida, retorna sin procesar)
- Para cada job, verifica el estado con Information Tracer API
- Si está `finished`, obtiene los resultados
- Guarda los resultados en GCS en la capa `raw/` (formato JSON)
- Actualiza el status del post a `done` en Firestore
- Actualiza el status del job a `done` en Firestore

### Fase 3: Convertir a Parquet (`/json-to-parquet`)
- Lee JSONs desde la capa `raw/` de GCS
- Convierte a formato Parquet optimizado
- Guarda en la capa `marts/replies/` de GCS
- **Carga incremental**: Solo procesa JSONs nuevos comparando `MAX(ingestion_timestamp)` del Parquet con `blob.updated` del JSON
- Fusiona nuevos registros con existentes (no sobreescribe)
- Deduplica por `(source_file, tweet_id)`
- Los datos quedan disponibles automáticamente en BigQuery para analytics

## Prerrequisitos

1. **Autenticación con GCP**
   ```bash
   gcloud auth application-default login
   ```

2. **Variables de entorno**
   
   Crea un archivo `.env` en la raíz del proyecto:
   ```bash
   # GCP Configuration
   GCP_PROJECT_ID=trust-481601
   FIRESTORE_DATABASE=socialnetworks
   FIRESTORE_COLLECTION=posts
   GCS_BUCKET_NAME=trust-dev
   
   # Information Tracer API
   INFORMATION_TRACER_API_KEY=tu-api-key-aqui
   ```

3. **Dependencias instaladas**
   ```bash
   poetry install
   ```

## Paso 1: Preparar datos de prueba en Firestore

Necesitas tener posts en Firestore con `status='noreplies'` para probar.

### Opción A: Usar posts existentes

Si ya tienes posts en Firestore, puedes verificar cuántos hay:
```bash
poetry run python -c "
from google.cloud import firestore
client = firestore.Client(project='trust-481601', database='socialnetworks')
posts = list(client.collection('posts').where('status', '==', 'noreplies').limit(10).stream())
print(f'Posts con status=noreplies: {len(posts)}')
for post in posts[:5]:
    print(f\"  - post_id: {post.to_dict().get('post_id')}, platform: {post.to_dict().get('platform')}\")
"
```

### Opción B: Crear posts de prueba

Puedes usar el script `upload_to_firestore.py` para subir posts de prueba (si tienes un CSV):
```bash
poetry run python scripts/upload_to_firestore.py \
  data/test-input.csv \
  posts \
  socialnetworks \
  trust-481601 \
  10
```

O crear posts manualmente con un script simple:
```python
# scripts/create_test_posts.py
from google.cloud import firestore
from datetime import datetime, timezone

client = firestore.Client(project='trust-481601', database='socialnetworks')

test_posts = [
    {
        'post_id': 'test_post_1',
        'platform': 'twitter',
        'country': 'test',
        'candidate_id': 'test_candidate',
        'status': 'noreplies',
        'created_at': datetime.now(timezone.utc),
        'replies_count': 50,
    },
    # Agregar más posts de prueba...
]

for post in test_posts:
    doc_ref = client.collection('posts').document()
    doc_ref.set(post)
    print(f"Created post: {post['post_id']}")
```

## Paso 2: Iniciar el servicio localmente

En una terminal, inicia el servicio:

```bash
# Activar el entorno virtual
poetry shell

# Iniciar el servicio (se ejecuta en http://localhost:8000)
uvicorn trust_api.scrapping_tools.main:app --reload --port 8000
```

Deberías ver algo como:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## Paso 3: Crear Jobs (Fase 1)

Esta fase hace submit de los posts a Information Tracer y guarda los hash_id en `pending_jobs`.

### Usando curl

```bash
# Crear jobs para 10 posts
curl -X POST "http://localhost:8000/process-posts?max_posts=10" \
  -H "Content-Type: application/json"
```

### Usando Python requests

```python
import requests

response = requests.post(
    "http://localhost:8000/process-posts",
    params={"max_posts": 10}
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

### Respuesta esperada

```json
{
  "processed": 10,
  "succeeded": 10,
  "failed": 0,
  "skipped": 0,
  "errors": [],
  "jobs_created": [
    {
      "job_id": "abc123...",
      "job_doc_id": "doc_id_1",
      "post_id": "post_id_1"
    },
    ...
  ]
}
```

### Verificar que los jobs se guardaron en Firestore

```bash
poetry run python -c "
from google.cloud import firestore
client = firestore.Client(project='trust-481601', database='socialnetworks')
jobs = list(client.collection('pending_jobs').where('status', '==', 'pending').stream())
print(f'Jobs pendientes: {len(jobs)}')
for job in jobs[:5]:
    data = job.to_dict()
    print(f\"  - job_id: {data.get('job_id')}, post_id: {data.get('post_id')}, created_at: {data.get('created_at')}\")
"
```

## Paso 4: Esperar a que los jobs terminen

Los jobs de Information Tracer pueden tardar varios minutos en completarse. Puedes:

### Opción A: Esperar manualmente (recomendado para testing)

Espera entre 5-10 minutos (dependiendo de la carga de Information Tracer) antes de ejecutar el Paso 5.

### Opción B: Verificar el estado de un job manualmente

Puedes verificar el estado de un job específico usando la API de Information Tracer:

```python
import requests
from trust_api.scrapping_tools.core.config import settings

job_id = "tu-job-id-aqui"  # Obtener del Paso 3
url = f"https://informationtracer.com/status?id_hash256={job_id}&token={settings.information_tracer_api_key}"

response = requests.get(url)
print(response.json())
```

Si el status es `"finished"`, puedes proceder al Paso 5.

## Paso 5: Procesar Jobs (Fase 2)

Esta fase consulta los jobs pendientes, verifica su estado, obtiene los resultados y los guarda en GCS.

### Usando curl

```bash
# Procesar todos los jobs pendientes
curl -X POST "http://localhost:8000/process-jobs" \
  -H "Content-Type: application/json"
```

O limitar a un número específico:

```bash
# Procesar máximo 10 jobs
curl -X POST "http://localhost:8000/process-jobs?max_jobs=10" \
  -H "Content-Type: application/json"
```

### Usando Python requests

```python
import requests

response = requests.post(
    "http://localhost:8000/process-jobs",
    params={"max_jobs": 10}  # Opcional
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

### Respuesta esperada

```json
{
  "processed": 10,
  "succeeded": 8,
  "failed": 0,
  "still_pending": 2,
  "errors": [],
  "saved_files": [
    "gs://trust-dev/raw/twitter/test_candidate/post_id_1.json",
    ...
  ],
  "log_file": "gs://trust-dev/logs/2025-01-15/10-30-45-123.json"
}
```

## Paso 6: Verificar resultados

### Verificar que los posts se actualizaron en Firestore

```bash
poetry run python -c "
from google.cloud import firestore
client = firestore.Client(project='trust-481601', database='socialnetworks')
posts = list(client.collection('posts').where('status', '==', 'done').limit(10).stream())
print(f'Posts procesados (status=done): {len(posts)}')
for post in posts[:5]:
    data = post.to_dict()
    print(f\"  - post_id: {data.get('post_id')}, updated_at: {data.get('updated_at')}\")
"
```

### Verificar que los jobs se actualizaron

```bash
poetry run python -c "
from google.cloud import firestore
client = firestore.Client(project='trust-481601', database='socialnetworks')
jobs_done = list(client.collection('pending_jobs').where('status', '==', 'done').stream())
jobs_pending = list(client.collection('pending_jobs').where('status', '==', 'pending').stream())
print(f'Jobs completados: {len(jobs_done)}')
print(f'Jobs pendientes: {len(jobs_pending)}')
"
```

### Verificar archivos en GCS (capa raw)

Los JSONs se guardan en la estructura: `raw/{country}/{platform}/{candidate_id}/{post_id}.json`

```bash
# Listar archivos JSON en la capa raw
gsutil ls -r gs://trust-dev/raw/

# Ver un archivo JSON específico (ajusta la ruta según tu estructura)
gsutil cat gs://trust-dev/raw/honduras/twitter/candidate_id/post_id.json | jq .

# Listar solo archivos de un país/plataforma específico
gsutil ls gs://trust-dev/raw/honduras/twitter/*/*.json
```

## Paso 7: Convertir JSONs a Parquet (Fase 3 - Opcional pero Recomendado)

Esta fase convierte los JSONs de la capa `raw/` a formato Parquet en la capa `marts/replies/` para analytics.

### Usando curl

```bash
# Convertir todos los JSONs nuevos a Parquet (carga incremental)
curl -X POST "http://localhost:8000/json-to-parquet" \
  -H "Content-Type: application/json"

# Filtrar por país y plataforma
curl -X POST "http://localhost:8000/json-to-parquet?country=honduras&platform=twitter" \
  -H "Content-Type: application/json"

# Filtrar por candidato específico
curl -X POST "http://localhost:8000/json-to-parquet?country=honduras&platform=twitter&candidate_id=test_candidate" \
  -H "Content-Type: application/json"

# Procesar todos los JSONs sin filtrar por timestamp (modo seguro)
curl -X POST "http://localhost:8000/json-to-parquet?skip_timestamp_filter=true" \
  -H "Content-Type: application/json"
```

### Usando Python requests

```python
import requests

# Convertir todos los JSONs nuevos (carga incremental)
response = requests.post("http://localhost:8000/json-to-parquet")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Filtrar por país y plataforma
response = requests.post(
    "http://localhost:8000/json-to-parquet",
    params={
        "country": "honduras",
        "platform": "twitter",
        "skip_timestamp_filter": False  # Usa optimización incremental (por defecto)
    }
)
print(response.json())

# Procesar todos los JSONs (modo seguro, sin filtro por timestamp)
response = requests.post(
    "http://localhost:8000/json-to-parquet",
    params={"skip_timestamp_filter": True}
)
print(response.json())
```

### Respuesta esperada

```json
{
  "processed": 8,
  "succeeded": 3,
  "failed": 0,
  "errors": [],
  "written_files": [
    "gs://trust-dev/marts/replies/ingestion_date=2026-01-09/platform=twitter/data.parquet",
    "gs://trust-dev/marts/replies/ingestion_date=2026-01-09/platform=instagram/data.parquet"
  ]
}
```

### Características del endpoint `/json-to-parquet`

- ✅ **Carga incremental**: Solo procesa JSONs nuevos comparando `MAX(ingestion_timestamp)` del Parquet con `blob.updated` del JSON
- ✅ **No sobreescribe**: Fusiona nuevos registros con existentes usando deduplicación
- ✅ **Deduplicación**: Evita duplicados por `(source_file, tweet_id)`
- ✅ **Eficiente**: Reduce I/O y procesamiento en 99% en ejecuciones incrementales típicas
- ✅ **Lazy loading**: Solo lee Parquet cuando encuentra JSONs para esa partición

**Nota sobre `skip_timestamp_filter`**:
- `false` (por defecto): Usa optimización incremental basada en `MAX(ingestion_timestamp)` del Parquet
- `true`: Procesa todos los JSONs sin filtrar por timestamp, confía solo en deduplicación (modo seguro)

Ver documentación completa en [JSON_TO_PARQUET_OPTIMIZATIONS.md](./JSON_TO_PARQUET_OPTIMIZATIONS.md).

### Verificar archivos Parquet en GCS (capa marts)

```bash
# Listar archivos Parquet en la capa marts
gsutil ls -r gs://trust-dev/marts/replies/

# Ver información de un archivo Parquet específico
gsutil stat gs://trust-dev/marts/replies/ingestion_date=2026-01-09/platform=twitter/data.parquet
```

## Script de prueba completo (Recomendado)

El proyecto incluye un script automatizado que hace todo el proceso:

### Opción 1: Script Python (Recomendado)

```bash
# Ejecutar el flujo completo (crear jobs, esperar 5 min, procesar jobs, convertir a Parquet)
poetry run python scripts/test_process_posts_flow.py

# Personalizar parámetros
poetry run python scripts/test_process_posts_flow.py \
  --max-posts 5 \
  --wait-minutes 3 \
  --base-url http://localhost:8000

# Solo ejecutar Fase 1 (crear jobs)
poetry run python scripts/test_process_posts_flow.py --only-phase1

# Solo ejecutar Fase 2 (procesar jobs - útil si ya esperaste)
poetry run python scripts/test_process_posts_flow.py --only-phase2 --skip-wait

# Solo ejecutar Fase 3 (convertir a Parquet)
poetry run python scripts/test_process_posts_flow.py --only-phase3

# Ejecutar Fase 2 y 3 (útil si ya creaste los jobs)
poetry run python scripts/test_process_posts_flow.py --only-phase2 --only-phase3 --skip-wait

# Ver todas las opciones
poetry run python scripts/test_process_posts_flow.py --help
```

### Opción 2: Script Bash

```bash
# Ejecutar el flujo completo
./scripts/test_process_posts_flow.sh

# Personalizar variables de entorno
BASE_URL=http://localhost:8000 \
MAX_POSTS=5 \
WAIT_MINUTES=3 \
./scripts/test_process_posts_flow.sh
```

## Troubleshooting

### Error: "INFORMATION_TRACER_API_KEY is not configured"

Verifica que la variable de entorno esté configurada:
```bash
echo $INFORMATION_TRACER_API_KEY
```

O en tu `.env`:
```bash
cat .env | grep INFORMATION_TRACER
```

### Error: "GCS_BUCKET_NAME is not configured"

Asegúrate de tener la variable `GCS_BUCKET_NAME` en tu `.env`:
```bash
export GCS_BUCKET_NAME=trust-dev
```

### Error: "Permission denied" al acceder a Firestore

Asegúrate de estar autenticado:
```bash
gcloud auth application-default login
```

### Los jobs quedan en estado "pending"

Esto es normal si los jobs aún no han terminado en Information Tracer. Puedes:
1. Esperar más tiempo
2. Ejecutar `/process-jobs` nuevamente
3. Verificar el estado manualmente con la API de Information Tracer

### Ver logs del servicio

Si el servicio está corriendo con `--reload`, los logs aparecerán en la terminal donde lo ejecutaste.

## Siguiente paso: Configurar Cloud Scheduler

Una vez que hayas probado localmente, puedes configurar Cloud Scheduler para automatizar el flujo completo:

### Flujo Recomendado con Cloud Scheduler

1. **Cada hora (00:00)**: Ejecutar `/process-posts?max_posts=10` (crear jobs)
   - Crea jobs en Information Tracer para posts con `status='noreplies'`
   - Actualiza posts a `status='processing'`

2. **Cada hora (05:00)**: Ejecutar `/process-jobs` (procesar jobs)
   - Procesa jobs con `status='pending'`
   - Guarda resultados en GCS `raw/` (JSONs)
   - Actualiza posts a `status='done'`
   - Verifica quota de Information Tracer antes de procesar (retorna si quota excedida)

3. **Diario (07:00)**: Ejecutar `/json-to-parquet?skip_timestamp_filter=false` (convertir a Parquet)
   - Convierte JSONs nuevos a formato Parquet
   - Carga incremental basada en `MAX(ingestion_timestamp)`
   - Guarda en GCS `marts/replies/`
   - Datos disponibles automáticamente en BigQuery para analytics

Esto da tiempo suficiente (5 minutos) para que los jobs se completen antes de procesarlos.

**Nota sobre `/json-to-parquet`**: El endpoint usa carga incremental por defecto (`skip_timestamp_filter=false`), comparando `MAX(ingestion_timestamp)` del Parquet con `blob.updated` del JSON. Si necesitas reprocesar todos los JSONs, usa `skip_timestamp_filter=true`.

Ver documentación en:
- [CONFIGURE_SCHEDULER.md](./GCP/CONFIGURE_SCHEDULER.md) - Configuración de Cloud Scheduler
- [JSON_TO_PARQUET_OPTIMIZATIONS.md](./JSON_TO_PARQUET_OPTIMIZATIONS.md) - Optimizaciones del endpoint `/json-to-parquet`

