# Crear el Job json-to-parquet-daily

El job `json-to-parquet-daily` no se creó automáticamente porque requiere que la variable `enable_cloud_scheduler` esté en `true`.

## Opción 1: Ejecutar Terraform Apply Manualmente (Recomendado)

Ejecuta terraform apply con la variable `enable_cloud_scheduler=true`:

```bash
cd terraform

terraform apply \
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="gcs_bucket=trust-prd" \
  -var="enable_cloud_scheduler=true" \
  -var="scrapping_tools_service_name=scrapping-tools" \
  -var="service_account_email=scheduler@trust-481601.iam.gserviceaccount.com"
```

Esto creará los 3 jobs:
- `process-posts-hourly`
- `process-jobs-hourly`  
- `json-to-parquet-daily` ⭐ (nuevo)

## Opción 2: Actualizar terraform.tfvars

Si tienes un archivo `terraform.tfvars`, agrega:

```hcl
enable_cloud_scheduler = true
scrapping_tools_service_name = "scrapping-tools"
service_account_email = "scheduler@trust-481601.iam.gserviceaccount.com"
```

Luego ejecuta:
```bash
cd terraform
terraform apply
```

## Opción 3: Importar Jobs Existentes y Aplicar (Recomendado si ya tienes jobs)

Si los jobs `process-posts-hourly` y `process-jobs-hourly` ya existen, necesitas importarlos al estado de Terraform primero:

```bash
cd terraform

# Usar el script de importación (más fácil)
./import_existing_jobs.sh

# O importar manualmente:
terraform import 'google_cloud_scheduler_job.process_posts[0]' projects/trust-481601/locations/us-east1/jobs/process-posts-hourly
terraform import 'google_cloud_scheduler_job.process_jobs[0]' projects/trust-481601/locations/us-east1/jobs/process-jobs-hourly

# Luego aplicar con enable_cloud_scheduler=true
terraform apply \
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="gcs_bucket=trust-prd" \
  -var="enable_cloud_scheduler=true" \
  -var="scrapping_tools_service_name=scrapping-tools" \
  -var="service_account_email=scheduler@trust-481601.iam.gserviceaccount.com"
```

**Nota**: Si ya ejecutaste `terraform apply` y el job `json-to-parquet-daily` se creó exitosamente (aunque los otros fallaron), solo necesitas importar los jobs existentes y ejecutar `terraform apply` nuevamente. Terraform solo creará/actualizará lo necesario.

## Verificar que el Job se Creó

Después de aplicar, verifica que el job existe:

```bash
# Ver el job
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1

# Ver todos los jobs
gcloud scheduler jobs list \
  --project=trust-481601 \
  --location=us-east1
```

## Ejecutar el Job Manualmente (Prueba)

Para probar el job manualmente:

```bash
gcloud scheduler jobs run json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

## Verificar Outputs de Terraform

Después de aplicar, verifica los outputs:

```bash
cd terraform
terraform output json_to_parquet_scheduler_job_name
terraform output json_to_parquet_endpoint_url
```

## Nota Importante

Si los otros jobs (`process-posts-hourly` y `process-jobs-hourly`) ya existen y fueron creados manualmente o con otra configuración, Terraform podría intentar recrearlos. En ese caso:

1. **Opción A**: Importar los jobs existentes al estado de Terraform antes de aplicar
2. **Opción B**: Crear solo el nuevo job manualmente con `gcloud` (ver abajo)

## Crear el Job Manualmente con gcloud (Alternativa)

Si prefieres no usar Terraform para este job específico:

```bash
# Obtener la URL del servicio scrapping-tools
SERVICE_URL=$(gcloud run services describe scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --format="value(status.url)")

# Crear el job
gcloud scheduler jobs create http json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1 \
  --schedule="0 7 * * *" \
  --time-zone="UTC" \
  --uri="${SERVICE_URL}/json-to-parquet" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@trust-481601.iam.gserviceaccount.com \
  --attempt-deadline=600s \
  --description="Convert JSONs to Parquet format daily by calling /json-to-parquet endpoint"
```

