# Testing /process-posts Endpoint Locally

Esta guía explica cómo probar el endpoint `/process-posts` del servicio **scrapping-tools** localmente antes de configurarlo con Cloud Scheduler.

**Nota:** El endpoint `/process-posts` está en el servicio `scrapping-tools`, no en `nlp-process`.

## Parámetros del Endpoint

El endpoint `/process-posts` acepta los siguientes parámetros de query:

- **`max_posts`** (opcional): Número máximo de posts a procesar. Si no se especifica, procesa todos los posts con `status='noreplies'`.
- **`sort_by`** (opcional, default: `"time"`): Orden de clasificación para las respuestas obtenidas de Information Tracer.
  - `"time"`: Ordenar por tiempo (cronológico)
  - `"engagement"`: Ordenar por engagement (interacción)
  
  **Nota:** El parámetro `sort_by` solo aplica a búsquedas por keyword, no a búsquedas por cuenta (account search).

## Prerrequisitos

1. **Autenticación con GCP**
   ```bash
   gcloud auth application-default login
   ```
   
   Esto permite que las librerías de Google Cloud (Firestore, GCS) usen tus credenciales localmente.

2. **Variables de entorno**
   
   Crea un archivo `.env` en la raíz del proyecto o exporta las variables:

   ```bash
   # Variables para scrapping-tools service
   GCP_PROJECT_ID=tu-project-id
   FIRESTORE_DATABASE=socialnetworks  # Opcional
   FIRESTORE_COLLECTION=posts  # Opcional
   GCS_BUCKET_NAME=trust-dev  # Requerido - debe especificarse según el ambiente
   
   # Information Tracer (servicio externo)
   INFORMATION_TRACER_URL=http://localhost:8081  # Para testing con mock
   INFORMATION_TRACER_TOKEN=mock-token  # Para testing con mock
   # O usar el servicio real:
   # INFORMATION_TRACER_URL=https://api.example.com
   # INFORMATION_TRACER_TOKEN=tu-token-real
   ```

3. **Servicio Mock (Opcional pero recomendado)**
   
   Para probar sin necesidad del servicio real, puedes usar el servicio mock incluido:
   
   ```bash
   # En una terminal separada
   ./scripts/start_mock_tracer.sh
   # O
   poetry run python scripts/mock_information_tracer.py
   ```
   
   El mock estará disponible en `http://localhost:8081/posts/{post_id}` y siempre devolverá un JSON válido.

   O exporta las variables en tu terminal:
   ```bash
   export GCP_PROJECT_ID=tu-project-id
   export SCRAPPING_TOOLS_URL=http://localhost:8082
   export GCS_BUCKET_NAME=trust-dev
   ```

3. **Instalar dependencias**
   ```bash
   poetry install
   ```

## Pasos para Probar

### 0. (Opcional) Iniciar el servicio Mock Information Tracer

Para testing local, puedes usar el mock:

```bash
# En una terminal separada
./scripts/start_mock_tracer.sh  # Corre en puerto 8081
```

### 1. Iniciar el servicio Scrapping Tools

En una terminal, configura las variables e inicia el servicio:

```bash
# Configurar variables
export GCP_PROJECT_ID=tu-project-id
export GCS_BUCKET_NAME=trust-dev
export INFORMATION_TRACER_URL=http://localhost:8081  # Mock o servicio real
export INFORMATION_TRACER_TOKEN=mock-token

# Iniciar servicio
poetry run uvicorn trust_api.scrapping_tools.main:app --reload --port 8082
```

Deberías ver algo como:
```
INFO:     Uvicorn running on http://127.0.0.1:8082 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
```

### 2. Verificar que el servicio está corriendo

En otra terminal:

```bash
curl http://localhost:8082/health
```

Deberías recibir:
```json
{"status":"healthy"}
```

### 3. Probar el endpoint

#### Opción A: Usando el script de prueba

```bash
chmod +x scripts/test_process_posts_local.sh
./scripts/test_process_posts_local.sh 8082
```

#### Opción B: Usando curl manualmente

```bash
# Procesar con valores por defecto (sort_by="time")
curl -X POST http://localhost:8082/process-posts \
  -H "Content-Type: application/json"

# Procesar máximo 50 posts ordenados por engagement
curl -X POST "http://localhost:8082/process-posts?max_posts_to_process=50&sort_by=engagement" \
  -H "Content-Type: application/json"

# Procesar máximo 10 posts ordenados por tiempo
curl -X POST "http://localhost:8082/process-posts?max_posts_to_process=10&sort_by=time" \
  -H "Content-Type: application/json"
```

#### Opción C: Usando Python

```python
import requests

# Procesar con valores por defecto
response = requests.post("http://localhost:8082/process-posts")
print(response.json())

# Procesar máximo 50 posts ordenados por engagement
response = requests.post(
    "http://localhost:8082/process-posts",
    params={"max_posts": 50, "sort_by": "engagement"}
)
print(response.json())

# Procesar máximo 10 posts ordenados por tiempo
response = requests.post(
    "http://localhost:8082/process-posts",
    params={"max_posts": 10, "sort_by": "time"}
)
print(response.json())
```

#### Opción D: Usando la documentación interactiva

Abre en tu navegador:
```
http://localhost:8082/docs
```

Busca el endpoint `POST /process-posts` y haz clic en "Try it out" → "Execute".

### 4. Verificar la respuesta

Una respuesta exitosa debería verse así:

```json
{
  "processed": 5,
  "succeeded": 4,
  "failed": 1,
  "skipped": 0,
  "errors": [
    "Error processing post_id=12345: HTTP 404 Not Found"
  ],
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

**Nota**: El endpoint `/process-posts` solo crea jobs (no espera resultados). Para obtener los resultados, debes ejecutar `/process-jobs` después de esperar a que los jobs se completen (ver [TESTING_PROCESS_POSTS_LOCAL.md](./TESTING_PROCESS_POSTS_LOCAL.md)).

## Verificar que los jobs se crearon en Firestore

```bash
# Listar jobs pendientes
poetry run python -c "
from google.cloud import firestore
client = firestore.Client(project='tu-project-id', database='socialnetworks')
jobs = list(client.collection('pending_jobs').where('status', '==', 'pending').limit(10).stream())
print(f'Jobs pendientes: {len(jobs)}')
for job in jobs[:5]:
    data = job.to_dict()
    print(f\"  - job_id: {data.get('job_id')}, post_id: {data.get('post_id')}\")
"
```

## Troubleshooting

### Error: "The query requires an index"
- En Firestore Native Mode, las queries simples (un solo filtro de igualdad) funcionan automáticamente sin índices compuestos.
- Si ves este error, verifica que estés usando Firestore Native Mode, no Datastore Mode.
- Para queries complejas en el futuro, Firestore te dará un link para crear el índice desde la consola cuando lo necesites.

### Error: "INFORMATION_TRACER_URL is not configured"
- Verifica que la variable `INFORMATION_TRACER_URL` esté configurada en `.env` o exportada.

### Error: "INFORMATION_TRACER_TOKEN is not configured"
- Verifica que la variable `INFORMATION_TRACER_TOKEN` esté configurada.

### Error: "GCS_BUCKET_NAME is not configured"
- Verifica que la variable `GCS_BUCKET_NAME` esté configurada.

### Error: "Permission denied" al acceder a Firestore/GCS
- Ejecuta: `gcloud auth application-default login`
- Verifica que tu cuenta tenga permisos en el proyecto GCP.

### Error: "No posts found"
- Verifica que existan documentos en Firestore con `status='noreplies'` en la colección `posts`.
- Puedes verificar con:
  ```bash
  python scripts/query_firestore.py posts --status noreplies --limit 5
  ```

### Error: "Service is not running"
- Asegúrate de que el servicio scrapping-tools esté corriendo en el puerto correcto (8082 por defecto).
- Verifica con: `curl http://localhost:8082/health`

## Prueba con datos de prueba

Si quieres probar sin datos reales en Firestore, puedes:

1. **Subir datos de prueba a Firestore:**
   ```bash
   python scripts/upload_to_firestore.py \
     data/test-input.csv \
     posts \
     socialnetworks \
     tu-project-id \
     10
   ```

2. **Verificar que se subieron:**
   ```bash
   python scripts/query_firestore.py posts --status noreplies --limit 5
   ```

3. **Ejecutar el endpoint:**
   ```bash
   curl -X POST http://localhost:8000/process-posts
   ```

## Flujo Completo de Procesamiento

El endpoint `/process-posts` es solo la **Fase 1** del flujo completo. El proceso completo incluye:

1. **Fase 1: Crear Jobs** (`/process-posts`)
   - Crea jobs en Information Tracer
   - Guarda `job_id` en Firestore `pending_jobs`

2. **Fase 2: Procesar Jobs** (`/process-jobs`)
   - Espera a que los jobs se completen (5-10 minutos)
   - Obtiene resultados de Information Tracer
   - Guarda JSONs en GCS `raw/`

3. **Fase 3: Convertir a Parquet** (`/json-to-parquet`)
   - Convierte JSONs a formato Parquet optimizado
   - Carga incremental basada en `MAX(ingestion_timestamp)`
   - Guarda en GCS `marts/replies/`
   - Datos disponibles en BigQuery para analytics

**Ver guía completa**: [TESTING_PROCESS_POSTS_LOCAL.md](./TESTING_PROCESS_POSTS_LOCAL.md) para probar todo el flujo localmente.

### Probar el flujo completo

```bash
# 1. Crear jobs
curl -X POST "http://localhost:8082/process-posts?max_posts_to_process=10"

# 2. Esperar 5-10 minutos, luego procesar jobs
curl -X POST "http://localhost:8082/process-jobs"

# 3. Convertir JSONs nuevos a Parquet (carga incremental)
curl -X POST "http://localhost:8082/json-to-parquet"
```

**Nota sobre `/json-to-parquet`**:
- Por defecto (`skip_timestamp_filter=false`): Solo procesa JSONs nuevos comparando `MAX(ingestion_timestamp)` del Parquet
- Modo seguro (`skip_timestamp_filter=true`): Procesa todos los JSONs sin filtrar por timestamp

Ver documentación completa en [JSON_TO_PARQUET_OPTIMIZATIONS.md](./JSON_TO_PARQUET_OPTIMIZATIONS.md).

## Siguiente paso

Una vez que hayas probado localmente y confirmado que funciona:

1. Despliega el servicio a Cloud Run
2. Configura Cloud Scheduler para automatizar las 3 fases:
   - Cada hora (00:00): `/process-posts?max_posts_to_process=10` (crear jobs)
   - Cada hora (05:00): `/process-jobs` (procesar jobs)
   - Diario (07:00): `/json-to-parquet?skip_timestamp_filter=false` (convertir a Parquet)

Ver documentación en [GCP/CONFIGURE_SCHEDULER.md](./GCP/CONFIGURE_SCHEDULER.md) para configurar Cloud Scheduler.

