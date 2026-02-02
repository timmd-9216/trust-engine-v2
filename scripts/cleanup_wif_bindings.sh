#!/bin/bash
# Script para eliminar bindings de WIF para repositorios que no existen

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Limpieza de bindings de WIF"
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
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var}"
SA_NAME="ci-deployer"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"
CORRECT_REPO="timmd-9216/trust-engine-v2"
OLD_REPO="hordia/trust-engine-v2"

echo "Configuración:"
echo "  Proyecto: ${PROJECT_ID}"
echo "  Service Account: ${SA_EMAIL}"
echo "  Repositorio correcto: ${CORRECT_REPO}"
echo "  Repositorio a eliminar: ${OLD_REPO}"
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
OLD_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${OLD_REPO}"

echo "Principal a eliminar:"
echo "  ${OLD_PRINCIPAL}"
echo ""

read -p "¿Eliminar los bindings para el repositorio ${OLD_REPO}? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelado."
  exit 0
fi

# Eliminar binding de workloadIdentityUser
echo ""
echo "1️⃣  Eliminando binding 'roles/iam.workloadIdentityUser' para ${OLD_REPO}..."
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${OLD_PRINCIPAL} AND bindings.role:roles/iam.workloadIdentityUser" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.workloadIdentityUser"; then
  echo "   Eliminando binding..."
  gcloud iam service-accounts remove-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${OLD_PRINCIPAL}" \
    --role="roles/iam.workloadIdentityUser" \
    --quiet || echo "   ⚠ Binding no existe o ya fue eliminado"
  echo -e "   ${GREEN}✓${NC} Binding eliminado (o no existía)"
else
  echo -e "   ${YELLOW}⚠${NC}  Binding no existe"
fi

# Eliminar binding de serviceAccountTokenCreator
echo ""
echo "2️⃣  Eliminando binding 'roles/iam.serviceAccountTokenCreator' para ${OLD_REPO}..."
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${OLD_PRINCIPAL} AND bindings.role:roles/iam.serviceAccountTokenCreator" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.serviceAccountTokenCreator"; then
  echo "   Eliminando binding..."
  gcloud iam service-accounts remove-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${OLD_PRINCIPAL}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --quiet || echo "   ⚠ Binding no existe o ya fue eliminado"
  echo -e "   ${GREEN}✓${NC} Binding eliminado (o no existía)"
else
  echo -e "   ${YELLOW}⚠${NC}  Binding no existe"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓${NC} Limpieza completada!"
echo "=========================================="
echo ""
echo "Ahora solo queda el repositorio correcto: ${CORRECT_REPO}"
echo ""
echo "Verifica los bindings:"
echo "  gcloud iam service-accounts get-iam-policy ${SA_EMAIL} --project=${PROJECT_ID} --format=yaml"

