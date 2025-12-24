#!/bin/bash
# Script to deploy Datastore composite indexes

set -e

# Get project ID from environment or command line
PROJECT_ID="${GCP_PROJECT_ID:-${1}}"
DATABASE="${DATABASE:-socialnetworks}"

if [ -z "$PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT_ID not set. Please provide it as an argument or set the environment variable."
    echo "Usage: $0 [PROJECT_ID]"
    exit 1
fi

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INDEX_FILE="$PROJECT_ROOT/index.yaml"

if [ ! -f "$INDEX_FILE" ]; then
    echo "Error: index.yaml not found at $INDEX_FILE"
    exit 1
fi

echo "Deploying Datastore indexes..."
echo "Project ID: $PROJECT_ID"
echo "Database: $DATABASE"
echo "Index file: $INDEX_FILE"
echo ""

# Deploy the indexes
gcloud datastore indexes create "$INDEX_FILE" \
    --project="$PROJECT_ID" \
    --database="$DATABASE"

echo ""
echo "Index deployment initiated. Check status with:"
echo "  gcloud datastore indexes list --project=$PROJECT_ID --database=$DATABASE"

