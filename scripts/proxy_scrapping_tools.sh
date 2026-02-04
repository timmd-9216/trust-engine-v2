#!/usr/bin/env bash
set -euo pipefail

# Proxy the scrapping-tools Cloud Run service locally
# This automatically handles authentication

# Cargar variables de entorno desde .env si existe
if [ -f .env ]; then
    # Exportar variables del .env ignorando comentarios y líneas vacías
    while IFS= read -r line || [ -n "$line" ]; do
        # Ignorar líneas vacías y comentarios
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Exportar solo líneas que contienen =
        if [[ "$line" =~ ^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*= ]]; then
            export "$line"
        fi
    done < .env
fi

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var}"
REGION="${GCP_REGION:-us-east1}"
SERVICE_NAME="scrapping-tools"
PORT="${PROXY_PORT:-8080}"

echo "Starting proxy for ${SERVICE_NAME} in project ${PROJECT_ID}, region ${REGION} on localhost:${PORT}..."
echo "Access the service at: http://localhost:${PORT}/docs"
echo ""
echo "Press Ctrl+C to stop the proxy"
echo ""

gcloud run services proxy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --port "${PORT}"

