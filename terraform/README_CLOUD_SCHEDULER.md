# Cloud Scheduler para `/process-posts` con Terraform

Este archivo Terraform crea un Cloud Scheduler job que ejecuta automáticamente el endpoint `/process-posts` del servicio `scrapping-tools` según un schedule configurado.

## Equivalente al script bash

Este archivo Terraform es equivalente a ejecutar:
```bash
./scripts/setup_cloud_scheduler.sh \
  trust-481601 \
  us-east1 \
  scrapping-tools \
  scheduler@trust-481601.iam.gserviceaccount.com
```

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
| `schedule` | Expresión cron (formato unix-cron) | `0 * * * *` (cada hora) |
| `job_name` | Nombre del job de Cloud Scheduler | `process-posts-hourly` |
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

- `0 * * * *` - Cada hora en el minuto 0
- `0 */2 * * *` - Cada 2 horas
- `0 9 * * *` - Todos los días a las 9:00 AM
- `0 9 * * 1` - Todos los lunes a las 9:00 AM
- `*/30 * * * *` - Cada 30 minutos

Para más información sobre el formato cron, ver: [Cron job format and time zone](https://cloud.google.com/scheduler/docs/configuring/cron-job-schedules)

## Verificar el job

Después de aplicar, puedes verificar el job con:

```bash
gcloud scheduler jobs describe process-posts-hourly \
  --project=trust-481601 \
  --location=us-east1
```

## Ejecutar manualmente

Para probar el job manualmente:

```bash
gcloud scheduler jobs run process-posts-hourly \
  --project=trust-481601 \
  --location=us-east1
```

## Outputs

Después de aplicar, Terraform mostrará:

- `scheduler_job_name`: Nombre del job creado
- `scheduler_job_id`: ID completo del recurso
- `endpoint_url`: URL completa que será llamada

## Eliminar el job

Para eliminar el job creado con Terraform:

```bash
terraform destroy
```

## Referencias

- [Documentación oficial: Schedule and run a cron job using Terraform](https://docs.cloud.google.com/scheduler/docs/schedule-run-cron-job-terraform)
- [Terraform Registry: google_cloud_scheduler_job](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_scheduler_job)

