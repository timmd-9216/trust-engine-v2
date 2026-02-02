#!/bin/bash
# Script para corregir problemas comunes de Workload Identity Federation

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Corrección de Workload Identity Federation"
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
PROVIDER="github-provider"
REPO="${GITHUB_REPO:-timmd-9216/trust-engine-v2}"  # Ajustar según tu repo

echo "Configuración:"
echo "  Proyecto: ${PROJECT_ID}"
echo "  Service Account: ${SA_EMAIL}"
echo "  Repositorio: ${REPO}"
echo "  Pool: ${POOL}"
echo "  Provider: ${PROVIDER}"
echo ""

read -p "¿Continuar con la corrección? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelado."
  exit 0
fi

# 1. Crear service account si no existe
echo ""
echo "1️⃣  Verificando service account..."
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "   Creando service account..."
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="CI Deployer" \
    --description="Service account for GitHub Actions deployments"
  echo -e "   ${GREEN}✓${NC} Service account creado"
else
  echo -e "   ${GREEN}✓${NC} Service account ya existe"
fi

# 2. Asignar roles al service account
echo ""
echo "2️⃣  Asignando roles al service account..."
ROLES=(
  "roles/run.admin"
  "roles/artifactregistry.admin"
  "roles/iam.serviceAccountUser"
  "roles/secretmanager.secretAccessor"
)

for role in "${ROLES[@]}"; do
  echo "   Verificando rol: ${role}..."
  if gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${SA_EMAIL} AND bindings.role:${role}" \
    --format="value(bindings.role)" 2>/dev/null | grep -q "${role}"; then
    echo -e "   ${GREEN}✓${NC} Ya tiene rol: ${role}"
  else
    echo "   Asignando rol: ${role}..."
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="${role}" \
      --condition=None
    echo -e "   ${GREEN}✓${NC} Rol asignado: ${role}"
  fi
done

# 3. Crear pool de WIF si no existe y obtener su nombre real
echo ""
echo "3️⃣  Verificando Workload Identity Pool..."
if ! gcloud iam workload-identity-pools describe "${POOL}" \
  --project="${PROJECT_ID}" \
  --location="global" >/dev/null 2>&1; then
  echo "   Creando pool..."
  gcloud iam workload-identity-pools create "${POOL}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --display-name="GitHub Actions Pool"
  echo -e "   ${GREEN}✓${NC} Pool creado"
else
  echo -e "   ${GREEN}✓${NC} Pool ya existe"
fi

# Obtener el nombre real del pool (resource name completo)
POOL_NAME=$(gcloud iam workload-identity-pools describe "${POOL}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -z "${POOL_NAME}" ]; then
  echo -e "   ${RED}✗${NC} No se pudo obtener el nombre del pool"
  exit 1
fi

echo "   Nombre del pool: ${POOL_NAME}"

# 4. Crear o actualizar provider
echo ""
echo "4️⃣  Verificando Workload Identity Provider..."
PROVIDER_EXISTS=false
CURRENT_ATTR_COND=""

if gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL}" >/dev/null 2>&1; then
  PROVIDER_EXISTS=true
  CURRENT_ATTR_COND=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL}" \
    --format="value(attributeCondition)" 2>/dev/null || echo "")
  EXPECTED_ATTR_COND="attribute.repository=='${REPO}'"
  
  if [ "${CURRENT_ATTR_COND}" != "${EXPECTED_ATTR_COND}" ]; then
    echo -e "   ${YELLOW}⚠${NC}  Provider existe pero attribute condition está incorrecto"
    echo "      Actual: ${CURRENT_ATTR_COND}"
    echo "      Esperado: ${EXPECTED_ATTR_COND}"
    echo ""
    read -p "   ¿Eliminar y recrear el provider con la configuración correcta? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      echo "   Eliminando provider..."
      gcloud iam workload-identity-pools providers delete "${PROVIDER}" \
        --project="${PROJECT_ID}" \
        --location="global" \
        --workload-identity-pool="${POOL}" \
        --quiet
      PROVIDER_EXISTS=false
    fi
  fi
fi

if [ "${PROVIDER_EXISTS}" = false ]; then
  echo "   Creando provider..."
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL}" \
    --display-name="GitHub Actions Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="attribute.repository=='${REPO}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"
  echo -e "   ${GREEN}✓${NC} Provider creado"
else
  echo -e "   ${GREEN}✓${NC} Provider ya existe y está configurado correctamente"
fi

# 5. Agregar bindings de IAM al service account
echo ""
echo "5️⃣  Configurando bindings de IAM en el service account..."

# Extraer el project number del pool name (formato: projects/PROJECT_NUMBER/...)
# O usar el PROJECT_ID directamente si el pool name no lo incluye
# El principal debe usar el formato correcto basado en el pool name real
if [[ "${POOL_NAME}" =~ projects/([0-9]+)/ ]]; then
  PROJECT_NUMBER="${BASH_REMATCH[1]}"
else
  # Si no podemos extraer el project number, usar PROJECT_ID
  # Necesitamos obtener el project number de otra forma
  PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "")
  if [ -z "${PROJECT_NUMBER}" ]; then
    echo -e "   ${RED}✗${NC} No se pudo obtener el project number"
    exit 1
  fi
fi

# Construir el principal usando el pool name real
# El pool name es algo como: projects/123456789/locations/global/workloadIdentityPools/github-pool
# El principal debe ser: principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/attribute.repository/REPO
POOL_ID=$(basename "${POOL_NAME}")
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"

echo "   Principal: ${PRINCIPAL}"

# Verificar binding de workloadIdentityUser
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${PRINCIPAL} AND bindings.role:roles/iam.workloadIdentityUser" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.workloadIdentityUser"; then
  echo -e "   ${GREEN}✓${NC} Binding 'roles/iam.workloadIdentityUser' ya existe"
else
  echo "   Agregando binding 'roles/iam.workloadIdentityUser'..."
  gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${PRINCIPAL}" \
    --role="roles/iam.workloadIdentityUser"
  echo -e "   ${GREEN}✓${NC} Binding agregado"
fi

# Verificar binding de serviceAccountTokenCreator
if gcloud iam service-accounts get-iam-policy "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:${PRINCIPAL} AND bindings.role:roles/iam.serviceAccountTokenCreator" \
  --format="value(bindings.role)" 2>/dev/null | grep -q "roles/iam.serviceAccountTokenCreator"; then
  echo -e "   ${GREEN}✓${NC} Binding 'roles/iam.serviceAccountTokenCreator' ya existe"
else
  echo "   Agregando binding 'roles/iam.serviceAccountTokenCreator'..."
  gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${PRINCIPAL}" \
    --role="roles/iam.serviceAccountTokenCreator"
  echo -e "   ${GREEN}✓${NC} Binding agregado"
fi

# 6. Mostrar el provider name para GitHub
echo ""
echo "6️⃣  Provider name para GitHub:"
PROVIDER_NAME=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL}" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -n "${PROVIDER_NAME}" ]; then
  echo ""
  echo "   Configura este valor en GitHub (environment: trust-engine):"
  echo "   Secret: GCP_WORKLOAD_IDENTITY_PROVIDER"
  echo "   Valor: ${PROVIDER_NAME}"
  echo ""
  echo "   También verifica que este secret esté configurado:"
  echo "   Secret: GCP_SERVICE_ACCOUNT_EMAIL"
  echo "   Valor: ${SA_EMAIL}"
else
  echo -e "   ${RED}✗${NC} No se pudo obtener el provider name"
fi

# 7. Verificar permisos de Secret Manager
echo ""
echo "7️⃣  Verificando permisos de Secret Manager..."
if gcloud secrets describe INFORMATION_TRACER_API_KEY \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "   El secreto existe, verificando permisos..."
  
  # Verificar si el service account tiene acceso
  if gcloud secrets get-iam-policy INFORMATION_TRACER_API_KEY \
    --project="${PROJECT_ID}" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${SA_EMAIL} AND bindings.role:roles/secretmanager.secretAccessor" \
    --format="value(bindings.role)" 2>/dev/null | grep -q "roles/secretmanager.secretAccessor"; then
    echo -e "   ${GREEN}✓${NC} Service account ya tiene acceso al secreto"
  else
    echo "   Agregando permiso al secreto..."
    gcloud secrets add-iam-policy-binding INFORMATION_TRACER_API_KEY \
      --project="${PROJECT_ID}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="roles/secretmanager.secretAccessor"
    echo -e "   ${GREEN}✓${NC} Permiso agregado"
  fi
else
  echo -e "   ${YELLOW}⚠${NC}  El secreto INFORMATION_TRACER_API_KEY no existe"
  echo "   Créalo manualmente con: ./scripts/create_secret_manager_secret.sh"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓${NC} Corrección completada!"
echo "=========================================="
echo ""
echo "Próximos pasos:"
echo "1. Verifica que los secrets en GitHub estén configurados correctamente:"
echo "   - GCP_WORKLOAD_IDENTITY_PROVIDER: ${PROVIDER_NAME}"
echo "   - GCP_SERVICE_ACCOUNT_EMAIL: ${SA_EMAIL}"
echo ""
echo "2. Ejecuta el script de verificación:"
echo "   ./scripts/verify_wif_setup.sh"
echo ""
echo "3. Si todo está correcto, ejecuta el workflow de GitHub Actions nuevamente."

