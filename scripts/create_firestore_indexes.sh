#!/bin/bash
# Script para crear índices de Firestore necesarios

set -e

PROJECT_ID="${GCP_PROJECT_ID:-trust-481601}"
DATABASE="${FIRESTORE_DATABASE:-socialnetworks}"

echo "=========================================="
echo "Creando índices de Firestore"
echo "=========================================="
echo ""
echo "Proyecto: ${PROJECT_ID}"
echo "Base de datos: ${DATABASE}"
echo ""

# Índice: status + created_at (para query de posts sin respuestas ordenados por fecha)
echo "1️⃣  Creando índice: posts - status + created_at..."
gcloud firestore indexes composite create \
  --project="${PROJECT_ID}" \
  --database="${DATABASE}" \
  --collection-group=posts \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING \
  2>&1 || echo "   (El índice puede ya existir)"

# Índice: status + platform + created_at (para query de posts de twitter priorizados)
echo "1️⃣  Creando índice: posts - status + platform + created_at..."
gcloud firestore indexes composite create \
  --project="${PROJECT_ID}" \
  --database="${DATABASE}" \
  --collection-group=posts \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=platform,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING \
  2>&1 || echo "   (El índice puede ya existir)"

# Índice: status + created_at (para query de jobs pendientes ordenados por fecha)
echo "2️⃣  Creando índice: pending_jobs - status + created_at..."
gcloud firestore indexes composite create \
  --project="${PROJECT_ID}" \
  --database="${DATABASE}" \
  --collection-group=pending_jobs \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=ASCENDING \
  2>&1 || echo "   (El índice puede ya existir)"

# Índice: status + updated_at (para query de jobs done ordenados por fecha de actualización)
echo "3️⃣  Creando índice: pending_jobs - status + updated_at..."
gcloud firestore indexes composite create \
  --project="${PROJECT_ID}" \
  --database="${DATABASE}" \
  --collection-group=pending_jobs \
  --query-scope=COLLECTION \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=updated_at,order=ASCENDING \
  2>&1 || echo "   (El índice puede ya existir)"

echo ""
echo "=========================================="
echo "Índices creados/verificados"
echo "=========================================="
echo ""
echo "Verifica el estado de los índices:"
echo "  gcloud firestore indexes composite list --project=${PROJECT_ID} --database=${DATABASE}"
echo ""
echo "Los índices pueden tardar unos minutos en estar listos."
echo "Puedes verificar el progreso en:"
echo "  https://console.firebase.google.com/project/${PROJECT_ID}/firestore/databases/${DATABASE}/indexes"

