# Cloud Run access control

Default behavior in this repo: deployments are private (`--no-allow-unauthenticated`). The deploy script and GitHub workflow also remove any existing `allUsers` binding so only principals with `roles/run.invoker` can call the service.

## Make the service public
```bash
gcloud run services add-iam-policy-binding $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --member="allUsers" \
  --role="roles/run.invoker"
```

## Revoke public access
```bash
gcloud run services remove-iam-policy-binding $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --member="allUsers" \
  --role="roles/run.invoker"
```

## Grant invoker to a specific identity

### Grant access to a user
```bash
gcloud run services add-iam-policy-binding $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --member="user:someone@example.com" \
  --role="roles/run.invoker"
```

### Grant access to a service account
```bash
gcloud run services add-iam-policy-binding $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --member="serviceAccount:sa@project.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## Example: Grant access to scrapping-tools service

### Grant access to specific user
```bash
# Replace your-email@example.com and $GCP_PROJECT_ID with your values
gcloud run services add-iam-policy-binding scrapping-tools \
  --project=$GCP_PROJECT_ID \
  --region=us-east1 \
  --member="user:your-email@example.com" \
  --role="roles/run.invoker"
```

After granting access, the user needs to authenticate with their Google account when accessing the service.

### Accessing via Browser

**If you get "Forbidden" error**, you need to authenticate with Google:

1. **Option A: Use Incognito/Private Window**
   - Open a new incognito/private window
   - Visit: `https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app/docs` (replace with your Cloud Run URL)
   - You'll be prompted to sign in with Google - use the account you granted access to
   - Accept the permissions

2. **Option B: Use Local Proxy (Recommended)**
   - This automatically handles authentication:
   ```bash
   ./scripts/proxy_scrapping_tools.sh
   ```
   - Then visit: `http://localhost:8080/docs` in your browser
   - The proxy handles all authentication automatically

### Accessing via curl

Use an identity token:
```bash
# Replace PROJECT_NUMBER with your GCP project number: gcloud projects describe $GCP_PROJECT_ID --format='value(projectNumber)'
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer ${TOKEN}" \
  https://scrapping-tools-PROJECT_NUMBER.us-east1.run.app/health

# Example: Call json-to-parquet endpoint
curl -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://scrapping-tools-PROJECT_NUMBER.us-east1.run.app/json-to-parquet?country=honduras"
```

### Verify current access permissions
```bash
gcloud run services get-iam-policy scrapping-tools \
  --project=$GCP_PROJECT_ID \
  --region=us-east1
```

### Revoke access from a specific user
```bash
gcloud run services remove-iam-policy-binding scrapping-tools \
  --project=$GCP_PROJECT_ID \
  --region=us-east1 \
  --member="user:your-email@example.com" \
  --role="roles/run.invoker"
```
