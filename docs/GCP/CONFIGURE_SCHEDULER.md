# Configurar Cloud Scheduler para `/process-posts`

Esta guía explica cómo configurar **Cloud Scheduler** para ejecutar automáticamente el endpoint `/process-posts` del servicio `scrapping-tools` cada hora, procesando 10 posts por ejecución.

**Ver también:** 
- [Information Tracer - Guía de Integración](../INFORMATION_TRACER.md) para entender cómo funciona Information Tracer y su API
- [Testing Process Posts Locally](../TESTING_PROCESS_POSTS_LOCAL.md) para probar el flujo localmente

## ¿Por qué Cloud Scheduler y no Cloud Workflows?

**Cloud Scheduler** es la mejor opción para este caso porque:
- ✅ Es simple: solo necesitas hacer un POST HTTP request
- ✅ Es económico: prácticamente gratis
- ✅ Es rápido de configurar
- ✅ Perfecto para tareas programadas simples

**Cloud Workflows** sería útil solo si necesitaras:
- Múltiples pasos secuenciales
- Lógica condicional compleja
- Orquestar varios servicios

Ver comparación completa en [SCHEDULER_VS_WORKFLOWS.md](./SCHEDULER_VS_WORKFLOWS.md).

## Prerrequisitos

1. El servicio `scrapping-tools` debe estar desplegado en Cloud Run
2. Debes tener permisos de administrador en el proyecto GCP
3. `gcloud` CLI debe estar instalado y configurado
4. Cloud Scheduler API debe estar habilitado (el script lo habilitará automáticamente si no lo está)

## Paso 1: Crear Service Account para Cloud Scheduler

Cloud Scheduler necesita un Service Account con permisos para invocar el servicio de Cloud Run.

```bash
PROJECT_ID="trust-481601"  # Ajusta según tu proyecto
REGION="us-east1"  # Ajusta según tu región
SA_NAME="cloud-scheduler-sa"  # Nombre del service account

# Crear el service account
gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name="Cloud Scheduler Service Account for process-posts"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
```

## Paso 3: Otorgar permisos al Service Account

El service account necesita permisos para invocar el servicio de Cloud Run:

```bash
SCRAPPING_TOOLS_SERVICE="scrapping-tools"  # Nombre de tu servicio Cloud Run

# Otorgar permiso para invocar el servicio Cloud Run
gcloud run services add-iam-policy-binding "${SCRAPPING_TOOLS_SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"
```

## Paso 4: Configurar Cloud Scheduler usando el script

El proyecto ya incluye un script para configurar Cloud Scheduler:

```bash
./scripts/setup_cloud_scheduler.sh \
  <project_id> \
  <region> \
  <scrapping_tools_service_name> \
  <service_account_email>
```

**Ejemplo completo:**

```bash
PROJECT_ID="trust-481601"
REGION="us-east1"
SCRAPPING_TOOLS_SERVICE="scrapping-tools"
SA_EMAIL="cloud-scheduler-sa@trust-481601.iam.gserviceaccount.com"

./scripts/setup_cloud_scheduler.sh \
  "${PROJECT_ID}" \
  "${REGION}" \
  "${SCRAPPING_TOOLS_SERVICE}" \
  "${SA_EMAIL}"
```

## Paso 5: Verificar la configuración

Ver los detalles del job:

```bash
gcloud scheduler jobs describe process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}"
```

## Paso 6: Probar manualmente (opcional)

Puedes ejecutar el job manualmente para probarlo:

```bash
gcloud scheduler jobs run process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}"
```

Ver el historial de ejecuciones:

```bash
gcloud scheduler jobs describe process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --format="value(state.lastExecutionTime, state.lastAttemptTime)"
```

## Configuración actual

El script configura:
- **Nombre del job**: `process-posts-hourly`
- **Schedule**: `0,30 * * * *` (cada 30 minutos, en los minutos 0 y 30)
- **Time Zone**: `UTC`
- **Método HTTP**: `POST`
- **Endpoint**: `{SERVICE_URL}/process-posts?max_posts=10` (procesa 10 posts por ejecución)
  - Ejemplo: `https://scrapping-tools-127336238226.us-east1.run.app/process-posts?max_posts=10`
- **Autenticación**: OIDC usando el Service Account especificado

### Flujo de dos fases

El sistema funciona en dos fases separadas para evitar sobrecargar Information Tracer:

1. **Fase 1 - Crear Jobs** (`/process-posts`): Hace submit de los posts a Information Tracer y guarda los hash_id en `pending_jobs`. Este proceso es rápido y no espera resultados.

2. **Fase 2 - Procesar Jobs** (`/process-jobs`): Consulta los jobs pendientes, verifica su estado, y cuando están listos obtiene los resultados. Se ejecuta después de que los jobs hayan tenido tiempo de procesarse.

Con esta configuración:
- **20 posts por hora** (10 posts cada 30 minutos) = submits rápidos sin esperar resultados
- Los jobs se procesan después (en la siguiente ejecución de `/process-jobs`)
- Esto distribuye la carga en el tiempo y evita bloqueos largos

## Modificar el schedule

Si necesitas cambiar el horario o el número de posts, puedes actualizar el schedule o la URL:

```bash
# Ejemplo: cambiar a cada 2 horas
gcloud scheduler jobs update http process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --schedule "0 */2 * * *" \
  --time-zone "UTC"

# Ejemplo: cambiar a 20 posts por ejecución
gcloud scheduler jobs update http process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --uri "${SERVICE_URL}/process-posts?max_posts=20"
```

### Formatos de schedule comunes

- `0,30 * * * *` - Cada 30 minutos (minutos 0 y 30) - default actual
- `0 * * * *` - Cada hora (minuto 0)
- `0 */2 * * *` - Cada 2 horas
- `0 */6 * * *` - Cada 6 horas
- `30 0 * * *` - Diariamente a las 00:30 UTC
- `0 0 * * 1` - Cada lunes a las 00:00 UTC
- `*/15 * * * *` - Cada 15 minutos

Más información: [Cloud Scheduler cron format](https://cloud.google.com/scheduler/docs/configuring/cron-job-schedules)

## Cambiar timezone

Para usar otra timezone (por ejemplo, America/Argentina/Buenos_Aires):

```bash
gcloud scheduler jobs update http process-posts-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --schedule "0 * * * *" \
  --time-zone "America/Argentina/Buenos_Aires"
```

## Eliminar el job

Si necesitas eliminar el job:

```bash
gcloud scheduler jobs delete process-posts-daily \
  --project "${PROJECT_ID}" \
  --location "${REGION}"
```

## Troubleshooting

### Error: "NOT_FOUND: Requested entity was not found"

Este error puede ocurrir por varias razones:

1. **Cloud Scheduler API no está habilitado:**
   ```bash
   # El script debería habilitarlo automáticamente, pero puedes habilitarlo manualmente:
   gcloud services enable cloudscheduler.googleapis.com --project="${PROJECT_ID}"
   ```

2. **Service Account no existe:**
   ```bash
   # Verificar que el service account existe
   gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${PROJECT_ID}"
   
   # Si no existe, créalo:
   gcloud iam service-accounts create scheduler \
     --project="${PROJECT_ID}" \
     --display-name="Cloud Scheduler Service Account"
   ```

3. **Problema con la región:**
   ```bash
   # Verificar que Cloud Scheduler está disponible en tu región
   gcloud scheduler locations list --project="${PROJECT_ID}"
   ```

### Error: "Permission denied" al invocar el servicio

Verifica que el service account tenga el rol `roles/run.invoker`:

```bash
gcloud run services get-iam-policy "${SCRAPPING_TOOLS_SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}"
```

### Error: "Service not found"

Verifica que el servicio Cloud Run existe y está desplegado:

```bash
gcloud run services describe "${SCRAPPING_TOOLS_SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}"
```

### Ver logs de ejecuciones

Para ver los logs cuando el job se ejecuta:

```bash
# Ver logs del servicio Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=${SCRAPPING_TOOLS_SERVICE}" \
  --project "${PROJECT_ID}" \
  --limit 50 \
  --format json
```

### El job no se ejecuta automáticamente

1. Verifica que el job esté habilitado:
   ```bash
   gcloud scheduler jobs describe process-posts-hourly \
     --project "${PROJECT_ID}" \
     --location "${REGION}" \
     --format="value(state)"
   ```

2. Si está `PAUSED`, habilítalo:
   ```bash
   gcloud scheduler jobs resume process-posts-hourly \
     --project "${PROJECT_ID}" \
     --location "${REGION}"
   ```

## Resumen de comandos útiles

```bash
# Crear service account
gcloud iam service-accounts create cloud-scheduler-sa --project=PROJECT_ID

# Otorgar permisos
gcloud run services add-iam-policy-binding scrapping-tools \
  --member="serviceAccount:cloud-scheduler-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Configurar scheduler (usa el script)
./scripts/setup_cloud_scheduler.sh PROJECT_ID REGION scrapping-tools SERVICE_ACCOUNT_EMAIL

# Ejecutar manualmente
gcloud scheduler jobs run process-posts-hourly --project=PROJECT_ID --location=REGION

# Ver estado
gcloud scheduler jobs describe process-posts-hourly --project=PROJECT_ID --location=REGION

# Ver logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=scrapping-tools" --limit=50
```

