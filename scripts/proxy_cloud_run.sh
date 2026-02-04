#!/usr/bin/env bash
set -euo pipefail

# Proxy a Cloud Run service locally using gcloud run services proxy.
# Expects environment variables (use .env or export manually):
#   GCP_PROJECT_ID
#   GCP_REGION
# Optional:
#   PROXY_PORT (default 8080) - solo cuando se usa --service
#
# Usage:
#   ./scripts/proxy_cloud_run.sh --service trust-engine-v2
#   ./scripts/proxy_cloud_run.sh --service scrapping-tools
#   ./scripts/proxy_cloud_run.sh --service nlp-process
#   ./scripts/proxy_cloud_run.sh --all
#   ./scripts/proxy_cloud_run.sh --help

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

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

require_env GCP_PROJECT_ID
require_env GCP_REGION

# Servicios disponibles y sus puertos
declare -A SERVICES=(
  ["trust-engine-v2"]="8080"
  ["scrapping-tools"]="8081"
  ["nlp-process"]="8082"
)

show_usage() {
  cat << EOF
Usage: $0 [OPTIONS]

Options:
  --service SERVICE    Proxy un servicio específico
                       Servicios disponibles: trust-engine-v2, scrapping-tools, nlp-process
  --all                Proxy todos los servicios en paralelo
  --help               Mostrar esta ayuda

Ejemplos:
  $0 --service trust-engine-v2
  $0 --service scrapping-tools
  $0 --service nlp-process
  $0 --all

Puertos asignados:
  trust-engine-v2:  8080
  scrapping-tools:  8081
  nlp-process:      8082
EOF
}

proxy_service() {
  local service="$1"
  local port="$2"
  
  if [ -z "${SERVICES[$service]:-}" ]; then
    echo "Error: Servicio desconocido: $service" >&2
    echo "Servicios disponibles: ${!SERVICES[*]}" >&2
    exit 1
  fi
  
  echo "Starting proxy for service ${service} in project ${GCP_PROJECT_ID}, region ${GCP_REGION} on localhost:${port}..."
  echo "Access the service at: http://localhost:${port}/docs"
  echo ""
  
  gcloud run services proxy "${service}" \
    --project "${GCP_PROJECT_ID}" \
    --region "${GCP_REGION}" \
    --port "${port}"
}

proxy_all_services() {
  echo "Starting proxies for all services..."
  echo "Press Ctrl+C to stop all proxies"
  echo ""
  
  local pids=()
  
  # Iniciar cada servicio en background
  for service in "${!SERVICES[@]}"; do
    local port="${SERVICES[$service]}"
    echo "Starting ${service} on port ${port}..."
    (
      gcloud run services proxy "${service}" \
        --project "${GCP_PROJECT_ID}" \
        --region "${GCP_REGION}" \
        --port "${port}" > /dev/null 2>&1
    ) &
    pids+=($!)
  done
  
  echo ""
  echo "All services are running:"
  for service in "${!SERVICES[@]}"; do
    local port="${SERVICES[$service]}"
    echo "  - ${service}: http://localhost:${port}/docs"
  done
  echo ""
  echo "Press Ctrl+C to stop all proxies"
  
  # Esperar a que todos los procesos terminen
  trap 'kill "${pids[@]}" 2>/dev/null; exit' INT TERM
  wait "${pids[@]}"
}

# Parsear argumentos
SERVICE=""
ALL=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --service)
      SERVICE="$2"
      shift 2
      ;;
    --all)
      ALL=true
      shift
      ;;
    --help|-h)
      show_usage
      exit 0
      ;;
    *)
      echo "Error: Opción desconocida: $1" >&2
      show_usage
      exit 1
      ;;
  esac
done

# Validar que se haya especificado una opción
if [ -z "$SERVICE" ] && [ "$ALL" = false ]; then
  echo "Error: Debes especificar --service o --all" >&2
  echo ""
  show_usage
  exit 1
fi

# Ejecutar según la opción
if [ "$ALL" = true ]; then
  proxy_all_services
else
  PORT="${SERVICES[$SERVICE]}"
  proxy_service "$SERVICE" "$PORT"
fi
