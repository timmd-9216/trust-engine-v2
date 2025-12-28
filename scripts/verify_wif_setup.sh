#!/bin/bash
# Script para verificar la configuración de Workload Identity Federation

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Verificación de Workload Identity Federation"
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
PROJECT_ID="${GCP_PROJECT_ID:-trust-481601}"
EXPECTED_SA="ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
REPO="${GITHUB_REPO:-timmd-9216/trust-engine-v2}"  # Ajustar según tu repo

# Intentar extraer pool y provider del GCP_WORKLOAD_IDENTITY_PROVIDER si está definido
if [ -n "${GCP_WORKLOAD_IDENTITY_PROVIDER}" ]; then
  # Extraer pool y provider del formato: projects/.../locations/global/workloadIdentityPools/POOL/providers/PROVIDER
  POOL=$(echo "${GCP_WORKLOAD_IDENTITY_PROVIDER}" | sed -n 's/.*workloadIdentityPools\/\([^/]*\)\/.*/\1/p')
  PROVIDER=$(echo "${GCP_WORKLOAD_IDENTITY_PROVIDER}" | sed -n 's/.*providers\/\([^/]*\)$/\1/p')
  echo "📋 Pool detectado: ${POOL}"
  echo "📋 Provider detectado: ${PROVIDER}"
else
  # Valores por defecto
  POOL="github-pool"
  PROVIDER="github-provider"
  echo "⚠️  GCP_WORKLOAD_IDENTITY_PROVIDER no está definido, usando valores por defecto"
fi

echo ""
echo "Proyecto: ${PROJECT_ID}"
echo "Service Account esperado: ${EXPECTED_SA}"
echo "Repositorio: ${REPO}"
echo "Pool: ${POOL}"
echo "Provider: ${PROVIDER}"
echo ""

ERRORS=0
WARNINGS=0

# 1. Verificar que el proyecto existe
echo "1️⃣  Verificando proyecto..."
if gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  echo -e "${GREEN}✓${NC} Proyecto ${PROJECT_ID} existe"
else
  echo -e "${RED}✗${NC} Proyecto ${PROJECT_ID} no existe o no tienes acceso"
  ((ERRORS++))
fi
echo ""

# 2. Verificar que el service account existe
echo "2️⃣  Verificando service account..."
if gcloud iam service-accounts describe "${EXPECTED_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo -e "${GREEN}✓${NC} Service account ${EXPECTED_SA} existe"
  
  # Verificar roles del service account
  echo "   Verificando roles del service account..."
  ROLES=$(gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${EXPECTED_SA}" \
    --format="value(bindings.role)" 2>/dev/null || echo "")
  
  REQUIRED_ROLES=("roles/run.admin" "roles/artifactregistry.admin" "roles/iam.serviceAccountUser" "roles/secretmanager.secretAccessor")
  for role in "${REQUIRED_ROLES[@]}"; do
    if echo "${ROLES}" | grep -q "${role}"; then
      echo -e "   ${GREEN}✓${NC} Tiene rol: ${role}"
    else
      echo -e "   ${YELLOW}⚠${NC}  Falta rol: ${role}"
      ((WARNINGS++))
    fi
  done
else
  echo -e "${RED}✗${NC} Service account ${EXPECTED_SA} no existe"
  echo "   Crear con: gcloud iam service-accounts create ci-deployer --project=${PROJECT_ID}"
  ((ERRORS++))
fi
echo ""

# 3. Verificar que el pool de WIF existe
echo "3️⃣  Verificando Workload Identity Pool..."
if gcloud iam workload-identity-pools describe "${POOL}" \
  --project="${PROJECT_ID}" \
  --location="global" >/dev/null 2>&1; then
  echo -e "${GREEN}✓${NC} Pool '${POOL}' existe"
else
  echo -e "${RED}✗${NC} Pool '${POOL}' no existe"
  echo "   Crear con: gcloud iam workload-identity-pools create ${POOL} --project=${PROJECT_ID} --location=global"
  ((ERRORS++))
fi
echo ""

# 4. Verificar que el provider existe
echo "4️⃣  Verificando Workload Identity Provider..."
if gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL}" >/dev/null 2>&1; then
  echo -e "${GREEN}✓${NC} Provider '${PROVIDER}' existe"
  
  # Verificar configuración del provider
  echo "   Verificando configuración del provider..."
  
  # Verificar issuer URI
  ISSUER=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL}" \
    --format="value(oidc.issuerUri)" 2>/dev/null || echo "")
  
  if [ "${ISSUER}" = "https://token.actions.githubusercontent.com" ]; then
    echo -e "   ${GREEN}✓${NC} Issuer URI correcto: ${ISSUER}"
  else
    echo -e "   ${YELLOW}⚠${NC}  Issuer URI: ${ISSUER} (esperado: https://token.actions.githubusercontent.com)"
    ((WARNINGS++))
  fi
  
  # Verificar attribute mapping
  ATTR_MAP=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL}" \
    --format="value(attributeMapping)" 2>/dev/null || echo "")
  
  if echo "${ATTR_MAP}" | grep -q "google.subject=assertion.sub" && \
     echo "${ATTR_MAP}" | grep -q "attribute.repository=assertion.repository"; then
    echo -e "   ${GREEN}✓${NC} Attribute mapping correcto"
  else
    echo -e "   ${YELLOW}⚠${NC}  Attribute mapping puede estar incompleto"
    echo "      Actual: ${ATTR_MAP}"
    echo "      Esperado: google.subject=assertion.sub,attribute.repository=assertion.repository"
    ((WARNINGS++))
  fi
  
  # Verificar attribute condition
  ATTR_COND=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL}" \
    --format="value(attributeCondition)" 2>/dev/null || echo "")
  
  EXPECTED_COND="attribute.repository=='${REPO}'"
  if [ "${ATTR_COND}" = "${EXPECTED_COND}" ]; then
    echo -e "   ${GREEN}✓${NC} Attribute condition correcto: ${ATTR_COND}"
  else
    echo -e "   ${YELLOW}⚠${NC}  Attribute condition puede estar incorrecto"
    echo "      Actual: ${ATTR_COND}"
    echo "      Esperado: ${EXPECTED_COND}"
    ((WARNINGS++))
  fi
else
  echo -e "${RED}✗${NC} Provider '${PROVIDER}' no existe"
  echo "   Crear con: gcloud iam workload-identity-pools providers create-oidc ${PROVIDER} ..."
  ((ERRORS++))
fi
echo ""

# 5. Verificar bindings de IAM en el service account
echo "5️⃣  Verificando bindings de IAM en el service account..."

# Obtener el nombre real del pool y extraer project number
POOL_NAME=$(gcloud iam workload-identity-pools describe "${POOL}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -n "${POOL_NAME}" ]; then
  # Extraer project number del pool name
  if [[ "${POOL_NAME}" =~ projects/([0-9]+)/ ]]; then
    PROJECT_NUMBER="${BASH_REMATCH[1]}"
  else
    # Obtener project number del proyecto
    PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "")
  fi
  
  if [ -n "${PROJECT_NUMBER}" ]; then
    POOL_ID=$(basename "${POOL_NAME}")
    PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
  else
    # Fallback al formato anterior
    PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"
  fi
else
  # Fallback si no podemos obtener el pool name
  PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}"
fi

IAM_BINDINGS=$(gcloud iam service-accounts get-iam-policy "${EXPECTED_SA}" \
  --project="${PROJECT_ID}" \
  --format="json" 2>/dev/null || echo "{}")

if echo "${IAM_BINDINGS}" | grep -q "roles/iam.workloadIdentityUser" && \
   echo "${IAM_BINDINGS}" | grep -q "${PRINCIPAL}"; then
  echo -e "${GREEN}✓${NC} Binding 'roles/iam.workloadIdentityUser' existe para el principal"
else
  echo -e "${RED}✗${NC} Falta binding 'roles/iam.workloadIdentityUser'"
  echo "   Agregar con:"
  echo "   gcloud iam service-accounts add-iam-policy-binding ${EXPECTED_SA} \\"
  echo "     --project=${PROJECT_ID} \\"
  echo "     --member=\"${PRINCIPAL}\" \\"
  echo "     --role=\"roles/iam.workloadIdentityUser\""
  ((ERRORS++))
fi

if echo "${IAM_BINDINGS}" | grep -q "roles/iam.serviceAccountTokenCreator" && \
   echo "${IAM_BINDINGS}" | grep -q "${PRINCIPAL}"; then
  echo -e "${GREEN}✓${NC} Binding 'roles/iam.serviceAccountTokenCreator' existe para el principal"
else
  echo -e "${RED}✗${NC} Falta binding 'roles/iam.serviceAccountTokenCreator'"
  echo "   Agregar con:"
  echo "   gcloud iam service-accounts add-iam-policy-binding ${EXPECTED_SA} \\"
  echo "     --project=${PROJECT_ID} \\"
  echo "     --member=\"${PRINCIPAL}\" \\"
  echo "     --role=\"roles/iam.serviceAccountTokenCreator\""
  ((ERRORS++))
fi
echo ""

# 6. Verificar que el provider name coincide con el secret de GitHub
echo "6️⃣  Verificando formato del provider name..."
# Obtener el provider name real
ACTUAL_PROVIDER_NAME=$(gcloud iam workload-identity-pools providers describe "${PROVIDER}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL}" \
  --format="value(name)" 2>/dev/null || echo "")

if [ -n "${ACTUAL_PROVIDER_NAME}" ]; then
  if [ -n "${GCP_WORKLOAD_IDENTITY_PROVIDER}" ]; then
    if [ "${GCP_WORKLOAD_IDENTITY_PROVIDER}" = "${ACTUAL_PROVIDER_NAME}" ]; then
      echo -e "${GREEN}✓${NC} GCP_WORKLOAD_IDENTITY_PROVIDER coincide con la configuración"
    else
      echo -e "${YELLOW}⚠${NC}  GCP_WORKLOAD_IDENTITY_PROVIDER no coincide"
      echo "   Configurado: ${GCP_WORKLOAD_IDENTITY_PROVIDER}"
      echo "   Esperado: ${ACTUAL_PROVIDER_NAME}"
      ((WARNINGS++))
    fi
  else
    echo -e "${YELLOW}⚠${NC}  GCP_WORKLOAD_IDENTITY_PROVIDER no está definido"
    echo "   Debe ser: ${ACTUAL_PROVIDER_NAME}"
    ((WARNINGS++))
  fi
else
  echo -e "${YELLOW}⚠${NC}  No se pudo obtener el provider name"
  ((WARNINGS++))
fi
echo ""

# 7. Verificar permisos de Secret Manager
echo "7️⃣  Verificando permisos de Secret Manager..."
if gcloud secrets get-iam-policy INFORMATION_TRACER_API_KEY \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo -e "${GREEN}✓${NC} Se puede acceder al secreto INFORMATION_TRACER_API_KEY"
  
  # Verificar que el service account tiene acceso
  SECRET_POLICY=$(gcloud secrets get-iam-policy INFORMATION_TRACER_API_KEY \
    --project="${PROJECT_ID}" \
    --format="json" 2>/dev/null || echo "{}")
  
  if echo "${SECRET_POLICY}" | grep -q "${EXPECTED_SA}" && \
     echo "${SECRET_POLICY}" | grep -q "roles/secretmanager.secretAccessor"; then
    echo -e "   ${GREEN}✓${NC} Service account tiene acceso al secreto"
  else
    echo -e "   ${YELLOW}⚠${NC}  Service account puede no tener acceso al secreto"
    echo "   Verificar con: gcloud secrets get-iam-policy INFORMATION_TRACER_API_KEY --project=${PROJECT_ID}"
    ((WARNINGS++))
  fi
else
  echo -e "${YELLOW}⚠${NC}  No se puede acceder al secreto INFORMATION_TRACER_API_KEY"
  echo "   (Esto es normal si el secreto no existe aún)"
  ((WARNINGS++))
fi
echo ""

# Resumen
echo "=========================================="
echo "Resumen"
echo "=========================================="
if [ ${ERRORS} -eq 0 ] && [ ${WARNINGS} -eq 0 ]; then
  echo -e "${GREEN}✓${NC} Todo está configurado correctamente!"
  exit 0
elif [ ${ERRORS} -eq 0 ]; then
  echo -e "${YELLOW}⚠${NC}  Configuración básica correcta, pero hay ${WARNINGS} advertencia(s)"
  echo "   Revisa las advertencias arriba"
  exit 0
else
  echo -e "${RED}✗${NC} Se encontraron ${ERRORS} error(es) y ${WARNINGS} advertencia(s)"
  echo "   Corrige los errores antes de continuar"
  exit 1
fi

