#!/usr/bin/env bash
set -euo pipefail

# Script para crear el secreto INFORMATION_TRACER_API_KEY en Secret Manager
# Esto debe ejecutarse una vez antes del primer deployment

# Cargar variables de entorno desde .env si existe
if [ -f .env ]; then
    # Exportar variables del .env ignorando comentarios y líneas vacías
    while IFS= read -r line; do
        # Ignorar líneas vacías y comentarios
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Exportar solo líneas que contienen =
        if [[ "$line" =~ ^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*= ]]; then
            export "$line"
        fi
    done < .env
fi

# Variables requeridas
PROJECT_ID="${GCP_PROJECT_ID:-}"
SECRET_NAME="INFORMATION_TRACER_API_KEY"
API_KEY="${INFORMATION_TRACER_API_KEY:-}"

# Validar que las variables estén configuradas
if [ -z "${PROJECT_ID}" ]; then
    echo "Error: GCP_PROJECT_ID no está configurado"
    echo "Configúralo en .env o como variable de entorno"
    exit 1
fi

if [ -z "${API_KEY}" ]; then
    echo "Error: INFORMATION_TRACER_API_KEY no está configurado"
    echo "Configúralo en .env o como variable de entorno"
    exit 1
fi

echo "Creando secreto ${SECRET_NAME} en Secret Manager..."
echo "Project: ${PROJECT_ID}"

# Verificar si el secreto ya existe
if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "⚠ El secreto ${SECRET_NAME} ya existe."
    read -p "¿Deseas actualizarlo con una nueva versión? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Creando nueva versión del secreto..."
        echo -n "${API_KEY}" | gcloud secrets versions add "${SECRET_NAME}" \
            --project="${PROJECT_ID}" \
            --data-file=-
        echo "✓ Nueva versión del secreto creada exitosamente"
    else
        echo "Operación cancelada. El secreto no fue modificado."
        exit 0
    fi
else
    echo "Creando nuevo secreto..."
    echo -n "${API_KEY}" | gcloud secrets create "${SECRET_NAME}" \
        --project="${PROJECT_ID}" \
        --replication-policy="automatic" \
        --data-file=-
    echo "✓ Secreto creado exitosamente"
fi

echo ""
echo "Próximos pasos:"
echo "1. Asegúrate de que el service account de Cloud Run tenga acceso al secreto:"
echo "   gcloud secrets add-iam-policy-binding ${SECRET_NAME} \\"
echo "     --project=${PROJECT_ID} \\"
echo "     --member=\"serviceAccount:TU_SERVICE_ACCOUNT@${PROJECT_ID}.iam.gserviceaccount.com\" \\"
echo "     --role=\"roles/secretmanager.secretAccessor\""
echo ""
echo "2. El workflow de GitHub Actions ahora podrá actualizar el secreto automáticamente"

