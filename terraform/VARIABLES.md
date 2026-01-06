# Terraform Variables Reference

Este documento lista todas las variables requeridas y opcionales para Terraform, con valores recomendados.

## Configuración en GitHub Actions

Configura estas variables en: **Settings → Secrets and variables → Actions → Variables** (environment: `trust-engine`)

---

## Variables Requeridas (sin valores por defecto)

### Core Infrastructure

| Variable | Tipo | Descripción | Valor Recomendado | Requerida Para |
|----------|------|-------------|-------------------|----------------|
| `GCP_PROJECT_ID` | Variable | GCP project ID | `trust-481601` | ✅ Todos los recursos |
| `GCP_REGION` | Variable | GCP region | `us-east1` | ✅ Todos los recursos |
| `GCS_BUCKET_NAME` | Variable | Bucket para datos (BigQuery external tables) | `trust-prd` | ✅ BigQuery |

### BigQuery (Siempre requerida)

| Variable | Tipo | Descripción | Valor Recomendado | Requerida Para |
|----------|------|-------------|-------------------|----------------|
| `GCS_BUCKET_NAME` | Variable | Bucket con Parquet files | `trust-prd` | ✅ BigQuery External Tables |

**Nota**: `GCS_BUCKET_NAME` ya está configurada como `trust-prd`.

### Cloud Scheduler (Opcional - solo si quieres crear Scheduler jobs)

| Variable | Tipo | Descripción | Valor Recomendado | Requerida Para |
|----------|------|-------------|-------------------|----------------|
| `SCRAPPING_TOOLS_SERVICE_NAME` | Variable | Nombre del Cloud Run service | `scrapping-tools` | ⚠️ Cloud Scheduler |
| `SERVICE_ACCOUNT_EMAIL` | Variable | Service account para OIDC | `ci-deployer@trust-481601.iam.gserviceaccount.com` | ⚠️ Cloud Scheduler |

### Workflow NLP (Opcional - solo si quieres crear Workflows)

| Variable | Tipo | Descripción | Valor Recomendado | Requerida Para |
|----------|------|-------------|-------------------|----------------|
| `SOURCE_BUCKET` | Variable | Bucket a monitorear | `trust-prd` | ⚠️ Workflow NLP |
| `OUTPUT_BUCKET` | Variable | Bucket para output | `trust-prd` | ⚠️ Workflow NLP |
| `TRUST_API_PROCESS_URL` | Variable | URL del endpoint de procesamiento | `https://trust-api-xxx.run.app/process` | ⚠️ Workflow NLP |

---

## Variables Opcionales (con valores por defecto)

Estas variables tienen valores por defecto y no necesitan configurarse a menos que quieras cambiarlas:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `bigquery_dataset` | `trust_analytics` | Nombre del dataset de BigQuery |
| `max_posts` | `10` | Máximo de posts a procesar por ejecución |
| `schedule` | `0 * * * *` | Cron schedule (cada hora) |
| `process_jobs_schedule` | `30 * * * *` | Cron schedule para process-jobs (minuto 30) |
| `job_name` | `process-posts-hourly` | Nombre del job de Scheduler |
| `process_jobs_job_name` | `process-jobs-hourly` | Nombre del job process-jobs |
| `time_zone` | `UTC` | Zona horaria |
| `source_prefix` | `""` | Prefijo opcional para filtrar objetos |
| `workflow_name` | `trust-api-workflow` | Nombre del workflow |
| `environment` | `prod` | Nombre del ambiente |

---

## Secrets Requeridos (Siempre)

| Secret | Descripción | Valor |
|--------|-------------|-------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider para autenticación | Configurado en GitHub |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Service account para Terraform | `ci-deployer@trust-481601.iam.gserviceaccount.com` |

---

## Configuración Mínima para BigQuery

Si solo quieres crear recursos de BigQuery (sin Scheduler/Workflow), necesitas:

### Variables (Settings → Variables):
- ✅ `GCP_PROJECT_ID` = `trust-481601`
- ✅ `GCP_REGION` = `us-east1`
- ✅ `GCS_BUCKET_NAME` = `trust-prd`

### Secrets (Settings → Secrets):
- ✅ `GCP_WORKLOAD_IDENTITY_PROVIDER`
- ✅ `GCP_SERVICE_ACCOUNT_EMAIL`

**Resultado**: Se crearán solo los recursos de BigQuery (dataset + external tables + vistas).

---

## Configuración Completa (BigQuery + Scheduler + Workflow)

Para crear todos los recursos, agrega además:

### Variables adicionales:
- ⚠️ `SCRAPPING_TOOLS_SERVICE_NAME` = `scrapping-tools`
- ⚠️ `SERVICE_ACCOUNT_EMAIL` = `ci-deployer@trust-481601.iam.gserviceaccount.com`
- ⚠️ `SOURCE_BUCKET` = `trust-prd`
- ⚠️ `OUTPUT_BUCKET` = `trust-prd`
- ⚠️ `TRUST_API_PROCESS_URL` = `https://trust-api-xxx.run.app/process`

---

## Cómo Verificar Variables Configuradas

```bash
# En GitHub Actions, las variables se pasan como:
terraform plan \
  -var="project_id=${GCP_PROJECT_ID}" \
  -var="region=${GCP_REGION}" \
  -var="gcs_bucket=${GCS_BUCKET_NAME}"
```

---

## Troubleshooting

### Error: "No value for required variable"

**Causa**: Falta una variable requerida.

**Solución**: 
1. Verifica que todas las variables requeridas estén en GitHub (Settings → Variables)
2. Si solo quieres BigQuery, las variables de Scheduler/Workflow no son necesarias (pero Terraform las requiere actualmente)

**Workaround temporal**: Hacer que los recursos de Scheduler/Workflow sean opcionales usando `count` o `for_each` condicionales.

---

## Recomendación

**Para empezar**: Configura solo las variables mínimas para BigQuery. Los recursos de Scheduler y Workflow pueden configurarse después si los necesitas.

