# Configurar Secret Manager para Cloud Run

Este documento explica cómo usar Google Cloud Secret Manager para almacenar secretos de forma segura en lugar de variables de entorno.

## ¿Por qué usar Secret Manager?

- ✅ **Seguridad**: Los secretos están encriptados y no son visibles en la configuración del servicio
- ✅ **Auditoría**: Puedes ver quién accedió a qué secretos y cuándo
- ✅ **Rotación**: Permite rotar secretos sin cambiar código
- ✅ **Control de acceso**: IAM granular por secreto

## Pasos para Configurar

### 1. Crear el secreto en Secret Manager

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

### 2. Dar permisos al Service Account de Cloud Run

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

### 3. Desplegar Cloud Run con el secreto

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

