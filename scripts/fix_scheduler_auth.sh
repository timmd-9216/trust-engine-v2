#!/usr/bin/env bash
# Script para diagnosticar y arreglar problemas de autenticación en Cloud Scheduler
# Verifica y corrige la configuración del scheduler para json-to-parquet

set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: $0 <project_id> <region> <job_name>" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  $0 trust-481601 us-east1 json-to-parquet-daily" >&2
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
JOB_NAME="$3"

echo "=========================================="
echo "Diagnosticando Cloud Scheduler Job: ${JOB_NAME}"
echo "=========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo ""

# Check if job exists
if ! gcloud scheduler jobs describe "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" >/dev/null 2>&1; then
  echo "❌ Error: Job '${JOB_NAME}' no existe" >&2
  exit 1
fi

echo "✓ Job existe"
echo ""

# Get job details
echo "Configuración actual del job:"
echo "----------------------------------------"
JOB_DETAILS=$(gcloud scheduler jobs describe "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --format=json)

echo "${JOB_DETAILS}" | jq -r '
  "HTTP Method: " + (.httpTarget.httpMethod // "NOT SET"),
  "URI: " + (.httpTarget.uri // "NOT SET"),
  "OIDC Service Account: " + (.httpTarget.oidcToken.serviceAccountEmail // "NOT SET"),
  "Schedule: " + (.schedule // "NOT SET")
'

echo ""
echo "----------------------------------------"
echo ""

# Extract current configuration
HTTP_METHOD=$(echo "${JOB_DETAILS}" | jq -r '.httpTarget.httpMethod // "GET"')
URI=$(echo "${JOB_DETAILS}" | jq -r '.httpTarget.uri // ""')
OIDC_SA=$(echo "${JOB_DETAILS}" | jq -r '.httpTarget.oidcToken.serviceAccountEmail // ""')
SCHEDULE=$(echo "${JOB_DETAILS}" | jq -r '.schedule // ""')
TIME_ZONE=$(echo "${JOB_DETAILS}" | jq -r '.timeZone // "UTC"')
ATTEMPT_DEADLINE=$(echo "${JOB_DETAILS}" | jq -r '.attemptDeadline // "600s"')

# Check for issues
ISSUES=0

if [ "${HTTP_METHOD}" != "POST" ]; then
  echo "❌ Problema detectado: HTTP Method es '${HTTP_METHOD}', debería ser 'POST'"
  ISSUES=$((ISSUES + 1))
fi

if [ -z "${OIDC_SA}" ]; then
  echo "❌ Problema detectado: No hay Service Account configurado para OIDC"
  ISSUES=$((ISSUES + 1))
fi

if [ -z "${URI}" ]; then
  echo "❌ Problema detectado: URI no está configurada"
  ISSUES=$((ISSUES + 1))
fi

# Check if service account has invoker permission
if [ -n "${OIDC_SA}" ]; then
  echo ""
  echo "Verificando permisos del service account: ${OIDC_SA}"
  
  # Extract service name from URI
  SERVICE_NAME=$(echo "${URI}" | sed -n 's|.*https://\([^.]*\)\.run\.app.*|\1|p')
  
  if [ -n "${SERVICE_NAME}" ]; then
    echo "Service name detectado: ${SERVICE_NAME}"
    
    # Check IAM policy
    IAM_POLICY=$(gcloud run services get-iam-policy "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --format=json 2>/dev/null || echo "{}")
    
    HAS_PERMISSION=$(echo "${IAM_POLICY}" | jq -r --arg sa "${OIDC_SA}" '
      .bindings[]? | 
      select(.role == "roles/run.invoker") | 
      .members[]? | 
      select(. == "serviceAccount:" + $sa)
    ')
    
    if [ -z "${HAS_PERMISSION}" ]; then
      echo "❌ Problema detectado: El service account '${OIDC_SA}' NO tiene permisos de invoker en el servicio '${SERVICE_NAME}'"
      ISSUES=$((ISSUES + 1))
    else
      echo "✓ El service account tiene permisos de invoker"
    fi
  fi
fi

echo ""
echo "=========================================="
if [ ${ISSUES} -eq 0 ]; then
  echo "✓ No se detectaron problemas"
  echo ""
  echo "Si aún así recibes errores 403, verifica:"
  echo "  1. Que el service account existe:"
  echo "     gcloud iam service-accounts describe ${OIDC_SA} --project ${PROJECT_ID}"
  echo ""
  echo "  2. Que el servicio Cloud Run existe:"
  echo "     gcloud run services describe ${SERVICE_NAME} --project ${PROJECT_ID} --region ${REGION}"
  echo ""
  echo "  3. Revisa los logs del scheduler:"
  echo "     gcloud logging read \"resource.type=cloud_scheduler_job AND resource.labels.job_id=${JOB_NAME}\" --project ${PROJECT_ID} --limit=10"
  exit 0
else
  echo "Se detectaron ${ISSUES} problema(s)"
  echo ""
  echo "¿Deseas arreglar automáticamente? (y/n)"
  read -r CONFIRM
  
  if [ "${CONFIRM}" != "y" ] && [ "${CONFIRM}" != "Y" ]; then
    echo "Cancelado. Ejecuta este script nuevamente cuando estés listo."
    exit 0
  fi
  
  echo ""
  echo "Arreglando configuración..."
  echo ""
  
  # Fix HTTP method if needed
  if [ "${HTTP_METHOD}" != "POST" ]; then
    echo "Actualizando HTTP method a POST..."
    gcloud scheduler jobs update http "${JOB_NAME}" \
      --project "${PROJECT_ID}" \
      --location "${REGION}" \
      --http-method POST
    echo "✓ HTTP method actualizado"
  fi
  
  # Fix OIDC if missing
  if [ -z "${OIDC_SA}" ]; then
    echo ""
    echo "❌ No se puede arreglar automáticamente: falta el service account"
    echo "Por favor, proporciona el email del service account:"
    read -r NEW_SA
    
    if [ -z "${NEW_SA}" ]; then
      echo "Error: Service account requerido" >&2
      exit 1
    fi
    
    echo "Actualizando OIDC service account..."
    gcloud scheduler jobs update http "${JOB_NAME}" \
      --project "${PROJECT_ID}" \
      --location "${REGION}" \
      --oidc-service-account-email "${NEW_SA}"
    echo "✓ OIDC service account actualizado"
    OIDC_SA="${NEW_SA}"
  fi
  
  # Grant invoker permission if needed
  if [ -n "${SERVICE_NAME}" ] && [ -z "${HAS_PERMISSION}" ]; then
    echo ""
    echo "Otorgando permisos de invoker al service account..."
    gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --member="serviceAccount:${OIDC_SA}" \
      --role="roles/run.invoker"
    echo "✓ Permisos otorgados"
  fi
  
  echo ""
  echo "=========================================="
  echo "✓ Configuración actualizada"
  echo ""
  echo "Verifica la nueva configuración:"
  echo "  gcloud scheduler jobs describe ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
  echo ""
  echo "Prueba ejecutando el job:"
  echo "  gcloud scheduler jobs run ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
fi

