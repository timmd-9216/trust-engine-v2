# Troubleshooting Cloud Run Authentication Errors

## Problem: 403 Unauthenticated Request

If you see errors like:
```
The request was not authenticated. Either allow unauthenticated invocations or set the proper Authorization header.
```

This means:
1. The Cloud Run service requires authentication (`--no-allow-unauthenticated`)
2. The request is missing an `Authorization` header
3. The caller doesn't have the `roles/run.invoker` permission

## Common Issues

### Issue 1: Wrong HTTP Method

**Error**: GET request to a POST endpoint

**Solution**: Use the correct HTTP method:
- `/json-to-parquet` requires `POST`, not `GET`
- `/process-posts` requires `POST`
- `/process-jobs` requires `POST`

### Issue 2: Missing Authentication Header

**Error**: Request without `Authorization` header

**Solution**: Authenticate the request using one of the methods below.

## Solutions

### Solution 1: Authenticate with gcloud (for manual testing)

```bash
# Get an identity token
TOKEN=$(gcloud auth print-identity-token)

# Make authenticated request
curl -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://scrapping-tools-uaozxzmkmq-ue.a.run.app/json-to-parquet?skip_timestamp_filter=true"
```

### Solution 2: Use gcloud run services proxy (for local testing)

```bash
# This automatically handles authentication
gcloud run services proxy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --port=8080

# Then call locally
curl -X POST "http://localhost:8080/json-to-parquet?skip_timestamp_filter=true"
```

### Solution 3: Grant Invoker Permission to a Service Account

If you're calling from another service (e.g., Cloud Scheduler, Cloud Functions, etc.):

```bash
# Grant permission to a service account
gcloud run services add-iam-policy-binding scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --member="serviceAccount:your-service-account@trust-481601.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

Then use the service account's identity token in your request.

### Solution 4: Allow Unauthenticated Access (NOT RECOMMENDED)

**Warning**: Only use this for testing or if the endpoint doesn't expose sensitive data.

```bash
# Allow unauthenticated access
gcloud run services add-iam-policy-binding scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

To revoke:
```bash
gcloud run services remove-iam-policy-binding scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

## Cloud Scheduler Configuration

If you're using Cloud Scheduler, ensure it's configured with OIDC authentication:

```hcl
http_target {
  uri         = "${service_url}/json-to-parquet?skip_timestamp_filter=false"
  http_method = "POST"

  oidc_token {
    service_account_email = "scheduler@trust-481601.iam.gserviceaccount.com"
  }
}
```

Verify the scheduler job:
```bash
gcloud scheduler jobs describe json-to-parquet-daily \
  --project=trust-481601 \
  --location=us-east1
```

## Node.js/JavaScript (got library)

If you're using the `got` library in Node.js:

```javascript
const got = require('got');
const { execSync } = require('child_process');

// Get identity token
const token = execSync('gcloud auth print-identity-token', { encoding: 'utf-8' }).trim();

// Make authenticated request
const response = await got.post('https://scrapping-tools-uaozxzmkmq-ue.a.run.app/json-to-parquet', {
  searchParams: { skip_timestamp_filter: 'true' },
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
```

Or use a service account key:
```javascript
const { GoogleAuth } = require('google-auth-library');

const auth = new GoogleAuth({
  scopes: ['https://www.googleapis.com/auth/cloud-platform']
});

const client = await auth.getIdTokenClient('https://scrapping-tools-uaozxzmkmq-ue.a.run.app');
const token = await client.idTokenProvider.fetchIdToken();

const response = await got.post('https://scrapping-tools-uaozxzmkmq-ue.a.run.app/json-to-parquet', {
  searchParams: { skip_timestamp_filter: 'true' },
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
```

## Python

```python
import requests
from google.auth import default
from google.auth.transport.requests import Request

# Get identity token
credentials, project = default()
request = Request()
credentials.refresh(request)
token = credentials.token

# Make authenticated request
response = requests.post(
    'https://scrapping-tools-uaozxzmkmq-ue.a.run.app/json-to-parquet',
    params={'skip_timestamp_filter': 'true'},
    headers={'Authorization': f'Bearer {token}'}
)
```

## Checking What's Making the Request

1. **Check Cloud Logging** for the trace ID:
   ```bash
   gcloud logging read "trace=projects/trust-481601/traces/1154e8f2585ae86fdb3a10e1fef27e46" \
     --project=trust-481601 \
     --limit=50
   ```

2. **Check Cloud Scheduler jobs**:
   ```bash
   gcloud scheduler jobs list --project=trust-481601 --location=us-east1
   ```

3. **Check for any external services** that might be calling the endpoint

## Verifying Service Configuration

Check if the service requires authentication:
```bash
gcloud run services describe scrapping-tools \
  --project=trust-481601 \
  --region=us-east1 \
  --format="value(spec.template.spec.containers[0].env)"
```

Check IAM bindings:
```bash
gcloud run services get-iam-policy scrapping-tools \
  --project=trust-481601 \
  --region=us-east1
```

## Related Documentation

- [Cloud Run Access Control](./ACCESS_CONTROL.md)
- [Deploy Scrapping Tools](./DEPLOY_SCRAPPING_TOOLS.md)
- [Cloud Scheduler Setup](../terraform/README_CLOUD_SCHEDULER.md)

