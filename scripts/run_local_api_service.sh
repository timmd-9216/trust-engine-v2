#!/usr/bin/env bash
set -euo pipefail

# Run a Trust API service locally with uvicorn (same ports as proxy_cloud_run.sh).
# Receives the same parameters as the Cloud Run service; no gcloud required.
#
# Usage:
#   ./scripts/run_local_api_service.sh --service nlp-process
#   ./scripts/run_local_api_service.sh --service trust-engine-v2
#   ./scripts/run_local_api_service.sh --service scrapping-tools
#   ./scripts/run_local_api_service.sh --help

# Cargar variables de entorno desde .env si existe
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" =~ ^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*= ]]; then
            export "$line"
        fi
    done < .env
fi

get_port() {
  case "$1" in
    trust-engine-v2)  echo "8080" ;;
    scrapping-tools)  echo "8081" ;;
    nlp-process)      echo "8082" ;;
    *)                echo "" ;;
  esac
}

get_app_module() {
  case "$1" in
    trust-engine-v2)  echo "trust_api.main:app" ;;
    scrapping-tools)  echo "trust_api.scrapping_tools.main:app" ;;
    nlp-process)      echo "trust_api.nlp.main:app" ;;
    *)                echo "" ;;
  esac
}

show_usage() {
  cat << EOF
Usage: $0 --service SERVICE

Runs the API service locally (same ports and contract as Cloud Run proxy).

Options:
  --service SERVICE    Service to run: trust-engine-v2, scrapping-tools, nlp-process
  --help               Show this help

Examples:
  $0 --service nlp-process
  $0 --service trust-engine-v2
  $0 --service scrapping-tools

Ports (same as proxy_cloud_run.sh):
  trust-engine-v2:  8080  -> http://localhost:8080/docs
  scrapping-tools:  8081  -> http://localhost:8081/docs
  nlp-process:      8082  -> http://localhost:8082/docs  (/, /health, /process, /analyze-corpus)
EOF
}

SERVICE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)
      show_usage
      exit 0
      ;;
    --service)
      if [ -z "${2:-}" ]; then
        echo "Error: --service requires a value." >&2
        exit 1
      fi
      case "$2" in
        trust-engine-v2|scrapping-tools|nlp-process) SERVICE="$2" ;;
        *)
          echo "Error: Unknown service: $2" >&2
          echo "Available: trust-engine-v2, scrapping-tools, nlp-process" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_usage >&2
      exit 1
      ;;
  esac
done

if [ -z "$SERVICE" ]; then
  echo "Error: --service is required." >&2
  show_usage >&2
  exit 1
fi

PORT=$(get_port "$SERVICE")
APP=$(get_app_module "$SERVICE")

if [ -z "$PORT" ] || [ -z "$APP" ]; then
  echo "Error: Unknown service: $SERVICE" >&2
  echo "Available: trust-engine-v2, scrapping-tools, nlp-process" >&2
  exit 1
fi

echo "Starting local API service [$SERVICE] on port ${PORT}..."
echo "App module: $APP"
echo "Docs: http://localhost:${PORT}/docs"
echo ""

exec poetry run uvicorn "$APP" --reload --reload-dir src --port "$PORT" --log-level info
