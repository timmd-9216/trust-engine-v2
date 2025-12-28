# Configurar Secret Manager para Cloud Run

Este documento explica cómo usar Google Cloud Secret Manager para almacenar secretos de forma segura en lugar de variables de entorno.

## Diagnóstico rápido

Si estás teniendo problemas con permisos de Secret Manager en GitHub Actions, primero verifica tu configuración de Workload Identity Federation:

```bash
# Verificar toda la configuración de WIF
./scripts/verify_wif_setup.sh

# Corregir problemas comunes de WIF
./scripts/fix_wif_setup.sh
```

Ver también: [Troubleshooting WIF](./WORKLOAD_IDENTITY.md#troubleshooting-wif-setup-errors)

## ¿Por qué usar Secret Manager?

- ✅ **Seguridad**: Los secretos están encriptados y no son visibles en la configuración del servicio
- ✅ **Auditoría**: Puedes ver quién accedió a qué secretos y cuándo
- ✅ **Rotación**: Permite rotar secretos sin cambiar código
- ✅ **Control de acceso**: IAM granular por secreto

## Pasos para Configurar

### 1. Crear el secreto manualmente (OBLIGATORIO)

**⚠️ Importante:** El secreto debe crearse manualmente antes del primer deployment. El workflow de GitHub Actions solo actualiza el secreto, no lo crea.

#### Opción A: Usar el script automatizado (Recomendado)

```bash
# Asegúrate de tener las variables en .env o exportadas
export GCP_PROJECT_ID=tu-project-id
export INFORMATION_TRACER_API_KEY=tu-api-key

# Ejecutar el script
./scripts/create_secret_manager_secret.sh
```

#### Opción B: Crear el secreto directamente

```bash
# Crear el secreto
echo -n "tu-api-key-aqui" | gcloud secrets create INFORMATION_TRACER_API_KEY \
  --project=tu-project-id \
  --replication-policy="automatic" \
  --data-file=-

# O si el secreto ya existe, actualizar su versión
echo -n "tu-api-key-aqui" | gcloud secrets versions add INFORMATION_TRACER_API_KEY \
  --project=tu-project-id \
  --data-file=-
```

### 2. Dar permisos a los Service Accounts (OBLIGATORIO)

Hay dos service accounts que necesitan permisos:

#### 2.1. Service Account de Cloud Run (para runtime)

El service account de Cloud Run necesita permiso para leer el secreto en runtime:

El service account de Cloud Run necesita permiso para acceder al secreto:

```bash
PROJECT_ID=tu-project-id
SERVICE_ACCOUNT=tu-service-account@${PROJECT_ID}.iam.gserviceaccount.com
SECRET_NAME=INFORMATION_TRACER_API_KEY

# Dar permiso al service account para acceder al secreto
gcloud secrets add-iam-policy-binding ${SECRET_NAME} \
  --project=${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

**Nota:** Si no especificas un service account al desplegar, Cloud Run usa el service account por defecto: `PROJECT_NUMBER-compute@developer.gserviceaccount.com`

Para encontrar el número de proyecto:
```bash
gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)"
```

#### 2.2. Service Account de GitHub Actions (para deployment)

El service account usado por GitHub Actions también necesita permisos para leer y actualizar el secreto durante el deployment:

```bash
PROJECT_ID=tu-project-id
# Este es el service account configurado en GCP_SERVICE_ACCOUNT_EMAIL de GitHub
GITHUB_ACTIONS_SA=tu-service-account@${PROJECT_ID}.iam.gserviceaccount.com
SECRET_NAME=INFORMATION_TRACER_API_KEY

# Dar permisos para leer y actualizar el secreto
gcloud secrets add-iam-policy-binding ${SECRET_NAME} \
  --project=${PROJECT_ID} \
  --member="serviceAccount:${GITHUB_ACTIONS_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

**Nota:** Necesitas `secretmanager.secretAccessor` para leer/actualizar el secreto. Si prefieres más control, puedes usar `secretmanager.secretVersionManager` que solo permite gestionar versiones, pero `secretAccessor` es suficiente para el workflow.

### 3. Verificar configuración de GitHub Secrets

**⚠️ Importante:** Asegúrate de que el secret `GCP_SERVICE_ACCOUNT_EMAIL` en GitHub (environment: `trust-engine`) esté configurado exactamente como:

```
ci-deployer@trust-481601.iam.gserviceaccount.com
```

**Verificación:**
1. Ve a GitHub → Settings → Environments → `trust-engine`
2. Verifica que el secret `GCP_SERVICE_ACCOUNT_EMAIL` tenga exactamente el valor arriba (sin espacios, sin comillas)
3. El workflow verificará automáticamente que coincida durante el deployment

Si el valor no coincide exactamente, el workflow fallará con un error de permisos aunque los permisos estén correctamente configurados en GCP.

### 4. El workflow actualizará el secreto automáticamente

Una vez creado el secreto manualmente, el workflow de GitHub Actions actualizará automáticamente el secreto en cada deployment con el valor del secret de GitHub. El workflow verificará que el secreto existe antes de intentar actualizarlo.

### 5. Desplegar Cloud Run con el secreto

El workflow desplegará Cloud Run con el secreto montado automáticamente:

En lugar de usar `--set-env-vars`, usa `--update-secrets`:

```bash
gcloud run deploy scrapping-tools \
  --project=tu-project-id \
  --region=us-east1 \
  --image=tu-imagen \
  --update-secrets=INFORMATION_TRACER_API_KEY=INFORMATION_TRACER_API_KEY:latest \
  --set-env-vars="APP_MODULE=trust_api.scrapping_tools.main:app,GCP_PROJECT_ID=tu-project-id"
```

**Sintaxis de `--update-secrets`:**
```
ENV_VAR_NAME=SECRET_NAME:VERSION
```

- `ENV_VAR_NAME`: Nombre de la variable de entorno en el contenedor
- `SECRET_NAME`: Nombre del secreto en Secret Manager
- `VERSION`: Versión del secreto (`latest` para la más reciente)

## Actualizar el Workflow de GitHub Actions

El workflow debe:
1. Crear/actualizar el secreto en Secret Manager (usando el secret de GitHub)
2. Desplegar Cloud Run usando `--update-secrets` en lugar de `--set-env-vars`

Ver el workflow actualizado en `.github/workflows/deploy-cloud-run.yml`

## Verificar que Funciona

Después de desplegar, verifica que el secreto esté montado:

```bash
# Ver la configuración del servicio
gcloud run services describe scrapping-tools \
  --project=tu-project-id \
  --region=us-east1 \
  --format="yaml(spec.template.spec.containers[0].env)"

# Deberías ver algo como:
# - name: INFORMATION_TRACER_API_KEY
#   valueFrom:
#     secretKeyRef:
#       key: latest
#       name: INFORMATION_TRACER_API_KEY
```

## Rotar un Secreto

Para rotar un secreto sin downtime:

```bash
# 1. Agregar una nueva versión del secreto
echo -n "nueva-api-key" | gcloud secrets versions add INFORMATION_TRACER_API_KEY \
  --project=tu-project-id \
  --data-file=-

# 2. Actualizar el servicio para usar la nueva versión
gcloud run services update scrapping-tools \
  --project=tu-project-id \
  --region=us-east1 \
  --update-secrets=INFORMATION_TRACER_API_KEY=INFORMATION_TRACER_API_KEY:latest
```

## Ventajas vs Variables de Entorno

| Aspecto | Variables de Entorno | Secret Manager |
|---------|---------------------|----------------|
| Encriptación | ❌ No | ✅ Sí |
| Visibilidad | ⚠️ Visible en configuración | ✅ Solo accesible en runtime |
| Auditoría | ❌ No | ✅ Sí |
| Rotación | ⚠️ Requiere redeploy | ✅ Sin redeploy |
| IAM | ⚠️ Limitado | ✅ Granular |

