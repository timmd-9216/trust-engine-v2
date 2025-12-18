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
```bash
gcloud run services add-iam-policy-binding $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --member="user:someone@example.com" \ # or serviceAccount:sa@project.iam.gserviceaccount.com
  --role="roles/run.invoker"
```
