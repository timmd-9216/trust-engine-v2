#!/bin/bash
# Script para corregir los bindings de WIF para el repositorio correcto

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Corrección de bindings de WIF"
echo "=========================================="
echo ""

# Cargar variables de entorno desde .env si existe
if [ -f .env ]; then
  echo "📄 Cargando variables desde .env..."
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

# Variables requeridas
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var or add to .env}"
SA_NAME="ci-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"
REPO="timmd-9216/trust-engine-v2"

echo "Configuración:"
echo "  Proyecto: ${PROJECT_ID}"
echo "  Service Account: ${SA_EMAIL}"
echo "  Repositorio: ${REPO}"
echo "  Pool: ${POOL}"
echo ""

# Obtener el nombre real del pool
POOL_NAME=$(gcloud iam workload-identity-pools describe "${POOL}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -z "${POOL_NAME}" ]; then
  echo -e "${RED}✗${NC} No se pudo obtener el nombre del pool"
  exit 1
fi

# Extraer project number del pool name
if [[ "${POOL_NAME}" =~ projects/([0-9]+)/ ]]; then
  PROJECT_NUMBER="${BASH_REMATCH[1]}"
else
  PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "")
  if [ -z "${PROJECT_NUMBER}" ]; then
    echo -e "${RED}✗${NC} No se pudo obtener el project number"
    exit 1
  fi
fi

POOL_ID=$(basename "${POOL_NAME}")
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"

echo "Principal a usar:"
echo "  ${PRINCIPAL}"
echo ""

read -p "¿Continuar con la corrección de bindings? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelado."
  exit 0
fi

# Verificar y agregar binding de workloadIdentityUser
echo ""
echo "1️⃣  Verificando binding 'roles/iam.workloadIdentityUser'..."
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${PRINCIPAL} AND bindings.role:roles/iam.workloadIdentityUser" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.workloadIdentityUser"; then
  echo -e "   ${GREEN}✓${NC} Binding ya existe"
else
  echo "   Agregando binding..."
  gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${PRINCIPAL}" \
    --role="roles/iam.workloadIdentityUser"
  echo -e "   ${GREEN}✓${NC} Binding agregado"
fi

# Verificar y agregar binding de serviceAccountTokenCreator
echo ""
echo "2️⃣  Verificando binding 'roles/iam.serviceAccountTokenCreator'..."
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${PRINCIPAL} AND bindings.role:roles/iam.serviceAccountTokenCreator" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.serviceAccountTokenCreator"; then
  echo -e "   ${GREEN}✓${NC} Binding ya existe"
else
  echo "   Agregando binding..."
  gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${PRINCIPAL}" \
    --role="roles/iam.serviceAccountTokenCreator"
  echo -e "   ${GREEN}✓${NC} Binding agregado"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓${NC} Corrección completada!"
echo "=========================================="
echo ""
echo "Próximos pasos:"
echo "1. Verifica que el provider tiene el attribute condition correcto:"
echo "   ./scripts/verify_wif_setup.sh"
echo ""
echo "2. Ejecuta el workflow de GitHub Actions nuevamente"

