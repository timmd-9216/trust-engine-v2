# Cloud Scheduler para `/process-posts`, `/process-jobs` y `/json-to-parquet` con Terraform

Este archivo Terraform crea tres Cloud Scheduler jobs:
1. **process-posts-hourly**: Ejecuta `/process-posts` cada hora en el minuto 0
2. **process-jobs-hourly**: Ejecuta `/process-jobs` cada hora en el minuto 30 (30 minutos después del primero)
3. **json-to-parquet-daily**: Ejecuta `/json-to-parquet` diariamente a las 7:00 AM UTC

## Flujo de dos fases

El sistema funciona en dos fases separadas:

1. **Fase 1 - Crear Jobs** (`/process-posts`): 
   - Se ejecuta cada hora en el minuto 0
   - Hace submit de posts a Information Tracer y guarda los hash_id en `pending_jobs`
   - Este proceso es rápido y no espera resultados

2. **Fase 2 - Procesar Jobs** (`/process-jobs`):
   - Se ejecuta cada hora en el minuto 30 (30 minutos después de la Fase 1)
   - Procesa todos los jobs pendientes en `pending_jobs`
   - Verifica el estado, descarga resultados y guarda en GCS

3. **Fase 3 - Convertir a Parquet** (`/json-to-parquet`):
   - Se ejecuta diariamente a las 7:00 AM UTC
   - Convierte JSONs nuevos de la capa `raw/` a formato Parquet en `processed/replies/`
   - Usa carga incremental optimizada (solo procesa JSONs nuevos)
   - No requiere filtros - procesa todos los países y plataformas

## Prerrequisitos

1. Terraform instalado (versión 1.0+)
2. `gcloud` CLI configurado con permisos adecuados
3. El servicio `scrapping-tools` debe estar desplegado en Cloud Run
4. Un Service Account con permisos `roles/run.invoker` en el servicio Cloud Run

## Uso

### 1. Inicializar Terraform

```bash
cd terraform
terraform init
```

### 2. Aplicar la configuración

```bash
terraform apply \
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="scrapping_tools_service_name=scrapping-tools" \
  -var="service_account_email=scheduler@trust-481601.iam.gserviceaccount.com"
```

### 3. Variables opcionales

Puedes personalizar el comportamiento con variables adicionales:

```bash
terraform apply \
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="scrapping_tools_service_name=scrapping-tools" \
  -var="service_account_email=scheduler@trust-481601.iam.gserviceaccount.com" \
  -var="max_posts=20" \
  -var="schedule=0 */2 * * *" \
  -var="job_name=process-posts-every-2-hours"
```

**Variables disponibles:**

| Variable | Descripción | Default |
|---------|-------------|---------|
| `project_id` | GCP project ID | (requerido) |
| `region` | Región de GCP | `us-east1` |
| `scrapping_tools_service_name` | Nombre del servicio Cloud Run | (requerido) |
| `service_account_email` | Email del service account para OIDC | (requerido) |
| `max_posts` | Máximo de posts a procesar por ejecución | `10` |
| `schedule` | Expresión cron para process-posts | `0 * * * *` (cada hora en minuto 0) |
| `job_name` | Nombre del job de Cloud Scheduler para process-posts | `process-posts-hourly` |
| `process_jobs_schedule` | Expresión cron para process-jobs | `30 * * * *` (cada hora en minuto 30) |
| `process_jobs_job_name` | Nombre del job de Cloud Scheduler para process-jobs | `process-jobs-hourly` |
| `json_to_parquet_schedule` | Expresión cron para json-to-parquet | `0 7 * * *` (diario a las 7 AM UTC) |
| `json_to_parquet_job_name` | Nombre del job de Cloud Scheduler para json-to-parquet | `json-to-parquet-daily` |
| `time_zone` | Zona horaria para el schedule | `UTC` |

### 4. Usar archivo de variables (opcional)

Puedes crear un archivo `terraform.tfvars`:

```hcl
project_id                  = "trust-481601"
region                      = "us-east1"
scrapping_tools_service_name = "scrapping-tools"
service_account_email       = "scheduler@trust-481601.iam.gserviceaccount.com"
max_posts                   = 10
schedule                    = "0 * * * *"
job_name                    = "process-posts-hourly"
time_zone                   = "UTC"
```

Luego simplemente ejecuta:
```bash
terraform apply
```

## Ejemplos de schedules

**Para process-posts:**
- `0 * * * *` - Cada hora en el minuto 0 (default)
- `0 */2 * * *` - Cada 2 horas
- `0 9 * * *` - Todos los días a las 9:00 AM

**Para process-jobs:**
- `30 * * * *` - Cada hora en el minuto 30 (default, 30 min después de process-posts)
- `15 * * * *` - Cada hora en el minuto 15
- `*/30 * * * *` - Cada 30 minutos

**Para json-to-parquet:**
- `0 7 * * *` - Diariamente a las 7:00 AM UTC (default)
- `0 8 * * *` - Diariamente a las 8:00 AM UTC
- `0 7 * * 1` - Cada lunes a las 7:00 AM UTC

**Nota:** Se recomienda mantener process-jobs al menos 30 minutos después de process-posts para dar tiempo a que los jobs se completen en Information Tracer. El job json-to-parquet se ejecuta diariamente y procesa todos los JSONs nuevos acumulados durante el día.

Para más información sobre el formato cron, ver: [Cron job format and time zone](https://cloud.google.com/scheduler/docs/configuring/cron-job-schedules)

## Verificar los jobs

Después de aplicar, puedes verificar ambos jobs:

```bash
# Verificar process-posts
gcloud scheduler jobs describe process-posts-hourly \
  --project=trust-481601 \
  --location=us-east1

# Verificar process-jobs
gcloud scheduler jobs describe process-jobs-hourly \
  --project=trust-481601 \
  --location=us-east1

# Verificar json-to-parquet
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

## Ejecutar manualmente

Para probar los jobs manualmente:

```bash
# Ejecutar process-posts
gcloud scheduler jobs run process-posts-hourly \
  --project=trust-481601 \
  --location=us-east1

# Ejecutar process-jobs
gcloud scheduler jobs run process-jobs-hourly \
  --project=trust-481601 \
  --location=us-east1

# Ejecutar json-to-parquet
gcloud scheduler jobs run json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

## Outputs

Después de aplicar, Terraform mostrará:

**Para process-posts:**
- `scheduler_job_name`: Nombre del job process-posts
- `scheduler_job_id`: ID completo del recurso process-posts
- `endpoint_url`: URL completa que será llamada para process-posts

**Para process-jobs:**
- `process_jobs_scheduler_job_name`: Nombre del job process-jobs
- `process_jobs_scheduler_job_id`: ID completo del recurso process-jobs
- `process_jobs_endpoint_url`: URL completa que será llamada para process-jobs

**Para json-to-parquet:**
- `json_to_parquet_scheduler_job_name`: Nombre del job json-to-parquet
- `json_to_parquet_scheduler_job_id`: ID completo del recurso json-to-parquet
- `json_to_parquet_endpoint_url`: URL completa que será llamada para json-to-parquet

## Eliminar el job

Para eliminar el job creado con Terraform:

```bash
terraform destroy
```

## Referencias

- [Documentación oficial: Schedule and run a cron job using Terraform](https://docs.cloud.google.com/scheduler/docs/schedule-run-cron-job-terraform)
- [Terraform Registry: google_cloud_scheduler_job](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_scheduler_job)

