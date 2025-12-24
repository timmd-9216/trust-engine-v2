# Google Cloud Datastore Configuration

This document describes the Datastore setup for storing social network posts in the `socialnetworks` database.

## Overview

The Datastore configuration stores social media posts with the following indexed fields:
- `platform`: Social media platform (e.g., "twitter")
- `conversation_id_str`: Unique conversation/post identifier
- `created_at`: Post creation timestamp
- `status`: Processing status (default: "scrapped")

## Prerequisites

- Google Cloud Project with Datastore API enabled
- `gcloud` CLI installed and authenticated
- Python 3.12+ with Poetry
- `google-cloud-datastore` library installed

### Enable Datastore API

```bash
gcloud services enable datastore.googleapis.com --project=YOUR_PROJECT_ID
```

### Install Dependencies

```bash
poetry add google-cloud-datastore
```

### Authentication

Ensure you're authenticated with Application Default Credentials:

```bash
gcloud auth application-default login
```

## Database Structure

- **Database Name**: `socialnetworks`
- **Entity Kind**: `social_post`
- **Key**: Uses `conversation_id_str` as the entity key (if available)

### Entity Schema

Each entity contains:
- `platform` (string): Social media platform identifier
- `conversation_id_str` (string): Unique post/conversation ID
- `created_at` (string): ISO timestamp of post creation
- `status` (string): Processing status, defaults to "scrapped"

## Uploading Data

### Using the Upload Script

The script `scripts/upload_to_datastore.py` uploads records from CSV to Datastore.

#### Basic Usage

```bash
# Upload first 10 records using default CSV path
python scripts/upload_to_datastore.py

# Specify CSV path, project ID, and limit
python scripts/upload_to_datastore.py \
    data/account_search-hnd01_rive.csv \
    YOUR_PROJECT_ID \
    10
```

#### Script Parameters

1. **CSV Path** (optional): Path to CSV file. Defaults to `data/account_search-hnd01_rive.csv`
2. **Project ID** (optional): GCP project ID. Can also be set via `GCP_PROJECT_ID` environment variable
3. **Limit** (optional): Number of records to upload. Defaults to 10

#### Example

```bash
# Upload first 50 records
python scripts/upload_to_datastore.py \
    data/account_search-hnd01_rive.csv \
    my-gcp-project \
    50
```

The script will:
- Read the CSV file
- Extract only the indexed fields (`platform`, `conversation_id_str`, `created_at`)
- Add the `status` field with value "scrapped"
- Upload entities to the `socialnetworks` database
- Display progress for each uploaded record

## Composite Indexes

Composite indexes are required for queries that filter or order by multiple properties. The `index.yaml` file defines all necessary composite indexes.

### Index Configuration

The following composite indexes are defined in `index.yaml`:

1. **Platform + Status**: Filter by platform and status
   ```yaml
   - kind: social_post
     properties:
       - name: platform
       - name: status
   ```

2. **Platform + Created At**: Filter by platform with date range queries
   ```yaml
   - kind: social_post
     properties:
       - name: platform
       - name: created_at
   ```

3. **Status + Created At**: Filter by status with date range queries
   ```yaml
   - kind: social_post
     properties:
       - name: status
       - name: created_at
   ```

4. **Platform + Status + Created At**: Comprehensive filtering
   ```yaml
   - kind: social_post
     properties:
       - name: platform
       - name: status
       - name: created_at
   ```

5. **Ordering Indexes**: For queries that order by `created_at` (descending) with filters
   - Platform + Created At (desc)
   - Status + Created At (desc)
   - Platform + Status + Created At (desc)

### When Composite Indexes Are Needed

Composite indexes are required for:
- Queries filtering on multiple properties
- Queries with inequality filters on multiple properties
- Queries ordering by a property while filtering on other properties

Single-property queries (e.g., `WHERE platform = 'twitter'`) don't require composite indexes.

## Deploying Indexes

### Using the Deployment Script

```bash
# Deploy indexes using helper script
./scripts/deploy_indexes.sh YOUR_PROJECT_ID

# Or with custom database name
DATABASE=socialnetworks ./scripts/deploy_indexes.sh YOUR_PROJECT_ID
```

### Using gcloud Directly

```bash
gcloud datastore indexes create index.yaml \
    --project=YOUR_PROJECT_ID \
    --database=socialnetworks
```

### Check Index Status

```bash
# List all indexes
gcloud datastore indexes list \
    --project=YOUR_PROJECT_ID \
    --database=socialnetworks

# Describe a specific index
gcloud datastore indexes describe INDEX_ID \
    --project=YOUR_PROJECT_ID \
    --database=socialnetworks
```

### Index Building

- Indexes are built asynchronously and may take several minutes
- Queries using these indexes will work once the indexes reach `READY` state
- Check index status regularly until all indexes are built

## Query Examples

### Python Query Examples

```python
from google.cloud import datastore

client = datastore.Client(project="YOUR_PROJECT_ID", database="socialnetworks")

# Query by platform
query = client.query(kind="social_post")
query.add_filter("platform", "=", "twitter")
results = list(query.fetch())

# Query by platform and status
query = client.query(kind="social_post")
query.add_filter("platform", "=", "twitter")
query.add_filter("status", "=", "scrapped")
results = list(query.fetch())

# Query with date range and ordering
from datetime import datetime
query = client.query(kind="social_post")
query.add_filter("platform", "=", "twitter")
query.add_filter("created_at", ">=", "2025-01-01")
query.order = ["-created_at"]  # Descending order
results = list(query.fetch(limit=100))

# Query by status and order by date
query = client.query(kind="social_post")
query.add_filter("status", "=", "scrapped")
query.order = ["-created_at"]
results = list(query.fetch())
```

### Supported Query Patterns

✅ **Supported** (with appropriate indexes):
- Filter by `platform` only
- Filter by `platform` and `status`
- Filter by `platform` and `created_at` (with range)
- Filter by `status` and `created_at` (with range)
- Filter by `platform`, `status`, and `created_at`
- Order by `created_at` with platform filter
- Order by `created_at` with status filter
- Order by `created_at` with platform and status filters

❌ **Not Supported** (would require additional indexes):
- Ordering by `platform` or `status`
- Complex queries with multiple inequality filters on different properties

## Troubleshooting

### Index Not Ready

If you see errors like "The query requires an index", ensure:
1. The index is defined in `index.yaml`
2. The index has been deployed
3. The index status is `READY` (check with `gcloud datastore indexes list`)

### Authentication Errors

If you see authentication errors:
```bash
# Re-authenticate
gcloud auth application-default login

# Verify credentials
gcloud auth application-default print-access-token
```

### Database Not Found

If the database doesn't exist, create it:
```bash
gcloud datastore databases create --database=socialnetworks --project=YOUR_PROJECT_ID
```

### CSV Parsing Issues

If the upload script fails to parse the CSV:
- Ensure the CSV file exists and is readable
- Check that the CSV has the required columns: `platform`, `conversation_id_str`, `created_at`
- Verify the CSV encoding is UTF-8

## Files Reference

- **Upload Script**: `scripts/upload_to_datastore.py`
- **Index Configuration**: `index.yaml`
- **Index Deployment Script**: `scripts/deploy_indexes.sh`
- **CSV Data**: `data/account_search-hnd01_rive.csv`

## Next Steps

1. Deploy the composite indexes before running complex queries
2. Upload data using the upload script
3. Verify data in the Datastore console
4. Test queries to ensure indexes are working correctly

