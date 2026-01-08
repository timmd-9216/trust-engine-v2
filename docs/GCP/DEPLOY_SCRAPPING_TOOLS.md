# Desplegar Scrapping Tools Service

Este documento explica cómo desplegar el servicio `scrapping-tools` a Cloud Run usando GitHub Actions o manualmente.

**Ver también:** [Information Tracer - Guía de Integración](../INFORMATION_TRACER.md) para entender cómo funciona Information Tracer y su API.

## Resumen

El servicio `scrapping-tools` se despliega usando la misma imagen Docker que los otros servicios, pero con una variable de entorno diferente (`APP_MODULE=trust_api.scrapping_tools.main:app`) para ejecutar el módulo correcto.

## Deployment Automático (GitHub Actions)

### Configurar Secrets/Variables en GitHub

Ve a tu repositorio → Settings → Secrets and variables → Actions → Variables (environment: `trust-engine`)

Agrega las siguientes variables:

**Obligatorias:**
- `GCP_SCRAPPING_TOOLS_SERVICE_NAME`: Nombre del servicio (ej: `scrapping-tools`)

**Opcionales pero recomendadas:**
- `INFORMATION_TRACER_URL`: URL del servicio externo Information Tracer
- `INFORMATION_TRACER_TOKEN`: Token de autenticación para Information Tracer
- `GCS_BUCKET_NAME`: Nombre del bucket de GCS donde se guardarán los archivos

**Nota:** Las variables `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_NAME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, y `GCP_SERVICE_ACCOUNT_EMAIL` ya deben estar configuradas para el deployment principal.

### Deployment Automático

El workflow se ejecuta automáticamente cuando:
- Haces push a la rama `main`
- Disparas el workflow manualmente desde GitHub Actions

El workflow:
1. Construye la imagen Docker (si no existe)
2. Despliega el servicio `scrapping-tools` a Cloud Run con:
   - `APP_MODULE=trust_api.scrapping_tools.main:app`
   - Variables de entorno configuradas
   - Acceso privado (no público)

## Deployment Manual

### Opción 1: Usando el script de deployment

```bash
export GCP_PROJECT_ID=trust-481601
export GCP_REGION=us-east1
export GCP_SERVICE_NAME=trust-engine-v2  # Nombre de la imagen base
export INFORMATION_TRACER_URL=https://api.example.com
export INFORMATION_TRACER_TOKEN=your-token
export GCS_BUCKET_NAME=trust-dev

# Construir y desplegar
./scripts/deploy_cloud_run.sh
```

Luego desplegar scrapping-tools con configuración personalizada:

```bash
# Primero, obtener la URL de la imagen más reciente
IMAGE_URL=$(gcloud artifacts docker images list \
  ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/cloud-run-source-deploy/${GCP_SERVICE_NAME} \
  --sort-by=CREATE_TIME \
  --limit=1 \
  --format="value(package)"):latest

# Desplegar scrapping-tools
gcloud run deploy scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --image "${IMAGE_URL}" \
  --platform managed \
  --no-allow-unauthenticated \
  --set-env-vars "APP_MODULE=trust_api.scrapping_tools.main:app,GCP_PROJECT_ID=${GCP_PROJECT_ID},INFORMATION_TRACER_URL=${INFORMATION_TRACER_URL},INFORMATION_TRACER_TOKEN=${INFORMATION_TRACER_TOKEN},GCS_BUCKET_NAME=${GCS_BUCKET_NAME}" \
  --memory 2Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --min-instances 0 \
  --port 8080
```

### Opción 2: Deployment directo con gcloud

```bash
PROJECT_ID=trust-481601
REGION=us-east1
SERVICE_NAME=scrapping-tools
IMAGE_NAME=us-east1-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/trust-engine-v2:latest

gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE_NAME}" \
  --platform managed \
  --no-allow-unauthenticated \
  --set-env-vars "APP_MODULE=trust_api.scrapping_tools.main:app,GCP_PROJECT_ID=${PROJECT_ID},INFORMATION_TRACER_URL=${INFORMATION_TRACER_URL},INFORMATION_TRACER_TOKEN=${INFORMATION_TRACER_TOKEN},GCS_BUCKET_NAME=${GCS_BUCKET_NAME}" \
  --memory 2Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --min-instances 0 \
  --port 8080
```

## Variables de Entorno

El servicio `scrapping-tools` requiere las siguientes variables de entorno:

### Obligatorias

- `GCS_BUCKET_NAME`: Nombre del bucket de GCS donde se guardarán los archivos JSON

### Opcionales (con valores por defecto)

- `GCP_PROJECT_ID`: ID del proyecto de GCP (puede detectarse automáticamente)
- `FIRESTORE_DATABASE`: Nombre de la base de datos Firestore (default: `socialnetworks`)
- `FIRESTORE_COLLECTION`: Nombre de la colección Firestore (default: `posts`)

### Opcionales (para servicio externo)

- `INFORMATION_TRACER_URL`: URL base del servicio Information Tracer
- `INFORMATION_TRACER_TOKEN`: Token de autenticación para Information Tracer

**Nota:** Si `INFORMATION_TRACER_URL` o `INFORMATION_TRACER_TOKEN` no están configurados, el endpoint `/posts/information` fallará, pero `/process-posts` puede funcionar si no hay posts que procesar.

## Verificar el Deployment

### Verificar que el servicio está corriendo

```bash
gcloud run services describe scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --format="value(status.url)"
```

### Hacer un health check

```bash
SERVICE_URL=$(gcloud run services describe scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --format="value(status.url)")

# Necesitas autenticarte primero
gcloud auth print-identity-token | \
  xargs -I {} curl -H "Authorization: Bearer {}" \
  "${SERVICE_URL}/health"
```

### Ver logs

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=scrapping-tools" \
  --project "${GCP_PROJECT_ID}" \
  --limit 50 \
  --format json
```

## Configurar Permisos para Cloud Scheduler

Después de desplegar el servicio, necesitas configurar los permisos para que Cloud Scheduler pueda invocarlo:

```bash
# Crear service account para Cloud Scheduler (si no existe)
gcloud iam service-accounts create cloud-scheduler-sa \
  --project "${GCP_PROJECT_ID}" \
  --display-name="Cloud Scheduler Service Account"

SA_EMAIL="cloud-scheduler-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

# Otorgar permiso para invocar scrapping-tools
gcloud run services add-iam-policy-binding scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"
```

Ver guía completa en [CONFIGURE_SCHEDULER.md](./CONFIGURE_SCHEDULER.md).

## Troubleshooting

### Error: Service not found

Verifica que el servicio esté desplegado:

```bash
gcloud run services list \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}"
```

### Error: Missing environment variables

Verifica las variables de entorno del servicio:

```bash
gcloud run services describe scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --format="value(spec.template.spec.containers[0].env)"
```

### Error: Permission denied

Asegúrate de que el service account tenga permisos para invocar el servicio:

```bash
gcloud run services get-iam-policy scrapping-tools \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}"
```

### El servicio no aparece en el workflow

Verifica que `GCP_SCRAPPING_TOOLS_SERVICE_NAME` esté configurado en GitHub:
- Ve a Settings → Secrets and variables → Actions
- Selecciona el environment `trust-engine`
- Verifica que la variable `GCP_SCRAPPING_TOOLS_SERVICE_NAME` exista y tenga un valor

## Arquitectura

El servicio `scrapping-tools` usa la misma imagen Docker que los otros servicios (main API y NLP service), pero se ejecuta con un módulo diferente:

```
┌─────────────────────────────────────┐
│     Docker Image (trust-engine-v2) │
│                                     │
│  ┌──────────────────────────────┐  │
│  │ Main Service                 │  │
│  │ APP_MODULE=trust_api.main    │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌──────────────────────────────┐  │
│  │ NLP Service                  │  │
│  │ APP_MODULE=trust_api.nlp     │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌──────────────────────────────┐  │
│  │ Scrapping Tools Service      │  │
│  │ APP_MODULE=trust_api.        │  │
│  │        scrapping_tools       │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

Esta arquitectura permite:
- ✅ Usar una sola imagen Docker para múltiples servicios
- ✅ Reducir el almacenamiento en Artifact Registry
- ✅ Asegurar que todos los servicios usen la misma versión del código
- ✅ Simplificar el mantenimiento y deployment

## Endpoints Disponibles

El servicio `scrapping-tools` expone los siguientes endpoints:

### `GET /health`
Health check del servicio.

### `POST /process-posts`
Envía jobs a Information Tracer API para posts con `status='noreplies'`.

### `GET /pending-jobs`
Consulta jobs pendientes sin procesarlos.

### `POST /process-jobs`
Procesa jobs pendientes, descarga resultados y guarda JSONs en GCS.

### `POST /fix-jobs`
Corrige jobs marcados como 'done' pero con JSONs vacíos en GCS.

### `POST /json-to-parquet` ⭐ Nuevo
Convierte JSONs de la capa `raw/` a formato Parquet en `processed/replies/` con **carga incremental optimizada**.

**Parámetros opcionales**:
- `country`: Filtrar por país (ej: `honduras`)
- `platform`: Filtrar por plataforma (ej: `twitter`, `instagram`)

### `GET /empty-result-jobs/count` ⭐ Nuevo
Cuenta jobs con status `empty_result` en Firestore con filtros opcionales.

**Parámetros opcionales**:
- `candidate_id`: Filtrar por candidate_id
- `platform`: Filtrar por platform (ej: `twitter`, `instagram`)
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

Ver documentación completa en [EMPTY_RESULT_JOBS.md](../../EMPTY_RESULT_JOBS.md).

### `POST /empty-result-jobs/retry` ⭐ Nuevo
Retry jobs con status `empty_result` moviéndolos a `pending` para reprocesarlos.

**Parámetros opcionales**:
- `candidate_id`: Filtrar por candidate_id
- `platform`: Filtrar por platform (ej: `twitter`, `instagram`)
- `country`: Filtrar por country
- `limit`: Máximo número de jobs a retry

**Respuesta:**
```json
{
  "total_found": 10,
  "retried": 10,
  "errors": [],
  "retried_jobs": [...]
}
```

Cuando estos jobs se procesen por `/process-jobs`, los logs mostrarán `is_retry: true` y `retry_count` para identificar reintentos.

Ver documentación completa en [EMPTY_RESULT_JOBS.md](../../EMPTY_RESULT_JOBS.md).
- `candidate_id`: Filtrar por candidato específico
- `skip_timestamp_filter`: Si es `true`, procesa todos los JSONs sin filtrar por timestamp (confía solo en deduplicación). Por defecto `false` (usa optimización de timestamp).

**Características**:
- ✅ **Carga incremental**: Solo procesa JSONs nuevos comparando timestamps
- ✅ **No sobreescribe**: Fusiona nuevos registros con existentes
- ✅ **Deduplicación**: Evita duplicados por `(source_file, tweet_id)`
- ✅ **Eficiente**: Reduce I/O y procesamiento en 99% en ejecuciones incrementales

**Ejemplo de uso**:
```bash
# Procesar todos los JSONs nuevos
curl -X POST "${SERVICE_URL}/json-to-parquet"

# Filtrar por país y plataforma
curl -X POST "${SERVICE_URL}/json-to-parquet?country=honduras&platform=twitter"

# Filtrar por candidato específico
curl -X POST "${SERVICE_URL}/json-to-parquet?country=honduras&platform=twitter&candidate_id=hnd01monc"

# Deshabilitar filtro por timestamp (procesa todos los JSONs, confía en deduplicación)
curl -X POST "${SERVICE_URL}/json-to-parquet?skip_timestamp_filter=true"
```

**Respuesta**:
```json
{
  "processed": 100,
  "succeeded": 3,
  "failed": 0,
  "errors": [],
  "written_files": [
    "gs://trust-prd/processed/replies/ingestion_date=2026-01-05/platform=twitter/data.parquet"
  ]
}
```

**Ver documentación completa**: [JSON_TO_PARQUET_OPTIMIZATIONS.md](../JSON_TO_PARQUET_OPTIMIZATIONS.md)

### Flujo Recomendado

```bash
# 1. Procesar jobs pendientes (genera JSONs en raw/)
POST /process-jobs

# 2. Convertir JSONs nuevos a Parquet (optimizado)
POST /json-to-parquet

# 3. Los datos están disponibles en BigQuery automáticamente
```

