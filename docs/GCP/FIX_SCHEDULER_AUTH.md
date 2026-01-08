# Arreglar Autenticación del Cloud Scheduler

## Problema

Cuando ejecutas el Cloud Scheduler job `json-to-parquet-daily`, recibes un error 403:

```
The request was not authenticated. Either allow unauthenticated invocations or set the proper Authorization header.
```

## Causas Comunes

1. **HTTP Method incorrecto**: El scheduler está usando GET en lugar de POST
2. **Falta OIDC Token**: El scheduler no tiene configurado el service account para autenticación
3. **Faltan permisos**: El service account no tiene el rol `roles/run.invoker` en el servicio Cloud Run

## Solución Rápida

### Opción 1: Usar el Script de Diagnóstico y Reparación (Recomendado)

```bash
# Diagnosticar y arreglar automáticamente
./scripts/fix_scheduler_auth.sh trust-481601 us-east1 json-to-parquet-daily
```

El script:
- Verifica la configuración actual del scheduler
- Detecta problemas (HTTP method, OIDC, permisos)
- Ofrece arreglar automáticamente los problemas encontrados

### Opción 2: Arreglar Manualmente

#### Paso 1: Verificar la Configuración Actual

```bash
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

#### Paso 2: Verificar el Service Account

```bash
# Ver qué service account está configurado
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1 \
  --format="value(httpTarget.oidcToken.serviceAccountEmail)"
```

#### Paso 3: Actualizar el Scheduler

Si el scheduler no tiene OIDC configurado o usa GET en lugar de POST:

```bash
# Obtener la URL del servicio
SERVICE_URL=$(gcloud run services describe scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --format="value(status.url)")

# Actualizar el scheduler
gcloud scheduler jobs update http json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1 \
  --uri="${SERVICE_URL}/json-to-parquet?skip_timestamp_filter=false" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@trust-481601.iam.gserviceaccount.com
```

**Nota**: Ajusta el email del service account según tu configuración.

#### Paso 4: Otorgar Permisos al Service Account

```bash
# Otorgar permisos de invoker
gcloud run services add-iam-policy-binding scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --member="serviceAccount:scheduler@trust-481601.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Nota**: Ajusta el email del service account según tu configuración.

#### Paso 5: Verificar

```bash
# Ver la configuración actualizada
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1

# Probar ejecutando el job
gcloud scheduler jobs run json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

## Verificar que Todo Está Correcto

### 1. Verificar Configuración del Scheduler

```bash
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1 \
  --format=json | jq -r '
    "HTTP Method: " + .httpTarget.httpMethod,
    "URI: " + .httpTarget.uri,
    "OIDC SA: " + .httpTarget.oidcToken.serviceAccountEmail
  '
```

Deberías ver:
- HTTP Method: `POST`
- URI: `https://scrapping-tools-XXXXX.run.app/json-to-parquet?skip_timestamp_filter=false`
- OIDC SA: `scheduler@trust-481601.iam.gserviceaccount.com` (o tu service account)

### 2. Verificar Permisos IAM

```bash
gcloud run services get-iam-policy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --format=json | jq -r '.bindings[] | select(.role == "roles/run.invoker") | .members[]'
```

Deberías ver el service account en la lista: `serviceAccount:scheduler@trust-481601.iam.gserviceaccount.com`

### 3. Verificar Logs

Después de ejecutar el job, revisa los logs:

```bash
# Ver logs del scheduler
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=json-to-parquet-daily" \
  --project=trust-481601 \
  --limit=10 \
  --format=json | jq -r '.[] | "\(.timestamp) - \(.jsonPayload.message // .textPayload)"'
```

## Reconfigurar Todos los Schedulers

Si necesitas reconfigurar todos los schedulers desde cero:

```bash
./scripts/setup_cloud_scheduler.sh \
  trust-481601 \
  us-east1 \
  scrapping-tools \
  scheduler@trust-481601.iam.gserviceaccount.com
```

Esto configurará:
- `process-posts-hourly`
- `process-jobs-hourly`
- `json-to-parquet-daily`

## Usar Terraform (Recomendado para Producción)

Si usas Terraform, asegúrate de que la configuración esté correcta:

```hcl
resource "google_cloud_scheduler_job" "json_to_parquet" {
  name             = "json-to-parquet-daily"
  description      = "Convert JSONs to Parquet format daily"
  schedule         = "0 7 * * *"
  time_zone        = "UTC"
  region           = "us-east1"
  attempt_deadline = "600s"

  http_target {
    uri         = "${service_url}/json-to-parquet?skip_timestamp_filter=false"
    http_method = "POST"

    oidc_token {
      service_account_email = "scheduler@trust-481601.iam.gserviceaccount.com"
    }
  }
}
```

Luego aplica:

```bash
cd terraform
terraform apply
```

## Troubleshooting Adicional

### El Service Account No Existe

Si el service account no existe, créalo:

```bash
gcloud iam service-accounts create scheduler \
  --project=trust-481601 \
  --display-name="Cloud Scheduler Service Account"
```

### El Scheduler Fue Creado Manualmente sin Autenticación

Si el scheduler fue creado manualmente sin OIDC, actualízalo:

```bash
gcloud scheduler jobs update http json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1 \
  --oidc-service-account-email=scheduler@trust-481601.iam.gserviceaccount.com
```

### Verificar que el Servicio Cloud Run Requiere Autenticación

```bash
gcloud run services describe scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --format="value(spec.template.metadata.annotations.'run.googleapis.com/ingress')"
```

Si ves `all` o `internal`, el servicio requiere autenticación (lo cual es correcto).

## Referencias

- [Cloud Run Access Control](./ACCESS_CONTROL.md)
- [Troubleshooting Authentication](./TROUBLESHOOTING_AUTHENTICATION.md)
- [Cloud Scheduler Setup](../terraform/README_CLOUD_SCHEDULER.md)

