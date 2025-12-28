# Workload Identity Federation for GitHub Actions

This project uses Workload Identity Federation (WIF) to let GitHub Actions impersonate a Google Cloud service account without storing JSON keys.

## Required values (GitHub secrets/vars)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: e.g. `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SERVICE_ACCOUNT_EMAIL`: e.g. `ci-deployer@PROJECT_ID.iam.gserviceaccount.com`
- `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_NAME`, `OPENROUTER_API_KEY`

## Minimal setup steps (gcloud)
```bash
PROJECT_ID=your-project
REGION=us-east1
POOL=github-pool
PROVIDER=github-provider
SA_NAME=ci-deployer
REPO="timmd-9216/trust-engine-v2"   # adjust to this repo (no github.com prefix)
POOL_NAME=$(gcloud iam workload-identity-pools describe $POOL --project=$PROJECT_ID --location=global --format='value(name)' || true)

gcloud iam service-accounts create $SA_NAME --project $PROJECT_ID
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.admin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud iam workload-identity-pools create $POOL \
  --project=$PROJECT_ID --location="global" \
  --display-name="GitHub Actions Pool"

gcloud iam workload-identity-pools providers create-oidc $PROVIDER \
  --project=$PROJECT_ID --location="global" \
  --workload-identity-pool=$POOL \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="attribute.repository=='${REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

gcloud iam service-accounts add-iam-policy-binding "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --role="roles/iam.workloadIdentityUser"
gcloud iam service-accounts add-iam-policy-binding "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --role="roles/iam.serviceAccountTokenCreator"

# Add Artifact Registry + Cloud Run roles to the deployer (project-level)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"
```

Then set the secrets in GitHub:
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: output of `gcloud iam workload-identity-pools providers describe $PROVIDER ... --format='value(name)'`
- `GCP_SERVICE_ACCOUNT_EMAIL`: `${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com`

## Artifact Registry repo and permissions
Create the Docker repo (one-time):
```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --project $PROJECT_ID \
  --location us-east1 \
  --repository-format=docker \
  --description="Docker repo for Cloud Run deployments"
```

Grant the Cloud Build SA push access (used by `gcloud builds submit`):
```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

Ensure the deploy service account (used in GitHub Actions) also has Artifact Registry permissions (already covered above via `roles/artifactregistry.admin`).

## Verificar configuración de WIF

### Script de verificación automática

Ejecuta el script de diagnóstico para verificar toda la configuración:

```bash
# Asegúrate de tener las variables en .env o exportadas
export GCP_PROJECT_ID=trust-481601
export GCP_WORKLOAD_IDENTITY_PROVIDER=projects/.../workloadIdentityPools/.../providers/...
export GITHUB_REPO=hordia/trust-engine-v2  # Ajustar según tu repo

# Ejecutar verificación
./scripts/verify_wif_setup.sh
```

El script verificará:
- ✅ Que el proyecto existe
- ✅ Que el service account existe y tiene los roles necesarios
- ✅ Que el pool de WIF existe
- ✅ Que el provider existe y está configurado correctamente
- ✅ Que los bindings de IAM están correctos
- ✅ Que el formato del provider name coincide con GitHub
- ✅ Que los permisos de Secret Manager están configurados

### Verificación manual paso a paso

#### 1. Verificar que el service account existe

```bash
gcloud iam service-accounts describe ci-deployer@trust-481601.iam.gserviceaccount.com \
  --project=trust-481601
```

#### 2. Verificar roles del service account

```bash
gcloud projects get-iam-policy trust-481601 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

Debes ver al menos:
- `roles/run.admin`
- `roles/artifactregistry.admin`
- `roles/iam.serviceAccountUser`
- `roles/secretmanager.secretAccessor` (para Secret Manager)

#### 3. Verificar que el pool de WIF existe

```bash
gcloud iam workload-identity-pools describe github-pool \
  --project=trust-481601 \
  --location=global
```

#### 4. Verificar que el provider existe y está configurado

```bash
gcloud iam workload-identity-pools providers describe github-provider \
  --project=trust-481601 \
  --location=global \
  --workload-identity-pool=github-pool \
  --format="yaml"
```

Verifica que:
- `oidc.issuerUri` sea `https://token.actions.githubusercontent.com`
- `attributeMapping` incluya `google.subject=assertion.sub` y `attribute.repository=assertion.repository`
- `attributeCondition` sea `attribute.repository=='timmd-9216/trust-engine-v2'` (ajustar según tu repo)

#### 5. Verificar bindings de IAM en el service account

```bash
gcloud iam service-accounts get-iam-policy ci-deployer@trust-481601.iam.gserviceaccount.com \
  --project=trust-481601 \
  --format="yaml"
```

Debes ver dos bindings con el principal:
```
principalSet://iam.googleapis.com/projects/trust-481601/locations/global/workloadIdentityPools/github-pool/attribute.repository/timmd-9216/trust-engine-v2
```

Con los roles:
- `roles/iam.workloadIdentityUser`
- `roles/iam.serviceAccountTokenCreator`

#### 6. Verificar el provider name en GitHub

El secret `GCP_WORKLOAD_IDENTITY_PROVIDER` en GitHub debe ser exactamente:

```bash
# Obtener el nombre completo del provider
gcloud iam workload-identity-pools providers describe github-provider \
  --project=trust-481601 \
  --location=global \
  --workload-identity-pool=github-pool \
  --format="value(name)"
```

Debería ser algo como:
```
projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider
```

#### 7. Verificar permisos de Secret Manager

```bash
# Ver quién tiene acceso al secreto
gcloud secrets get-iam-policy INFORMATION_TRACER_API_KEY \
  --project=trust-481601
```

Debes ver que `ci-deployer@trust-481601.iam.gserviceaccount.com` tiene el rol `roles/secretmanager.secretAccessor`.

## Troubleshooting WIF setup errors

### Error: `PERMISSION_DENIED` al acceder a Secret Manager

**Síntomas:**
- El workflow falla con `Permission 'secretmanager.secrets.get' denied`
- El service account parece tener los permisos correctos

**Soluciones:**

1. **Verificar que el secret en GitHub coincide exactamente:**
   ```bash
   # El secret GCP_SERVICE_ACCOUNT_EMAIL debe ser exactamente:
   ci-deployer@trust-481601.iam.gserviceaccount.com
   ```
   Sin espacios, sin comillas, sin caracteres extra.

2. **Verificar que los permisos están en el secreto, no solo en el proyecto:**
   ```bash
   gcloud secrets add-iam-policy-binding INFORMATION_TRACER_API_KEY \
     --project=trust-481601 \
     --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```

3. **Esperar propagación de permisos:**
   Los permisos de IAM pueden tardar 1-3 minutos en propagarse. Espera unos minutos y vuelve a intentar.

4. **Verificar Workload Identity Federation:**
   Si los permisos están correctos pero aún falla, puede ser un problema con WIF:
   - Verifica que el provider name en GitHub sea exactamente el correcto
   - Verifica que el attribute condition coincida con tu repo
   - Ejecuta `./scripts/verify_wif_setup.sh` para diagnóstico completo

5. **Verificar autenticación en el workflow:**
   El workflow debe tener `permissions: id-token: write` para que WIF funcione.

### Error: `INVALID_ARGUMENT: The attribute condition must reference one of the provider's claims`

**Causa:** El provider no tiene el `attribute-mapping` correcto o el `attribute-condition` no coincide.

**Solución:**
```bash
# Recrear el provider con la configuración correcta
gcloud iam workload-identity-pools providers delete github-provider \
  --project=trust-481601 \
  --location=global \
  --workload-identity-pool=github-pool

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --project=trust-481601 \
  --location=global \
  --workload-identity-pool=github-pool \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="attribute.repository=='timmd-9216/trust-engine-v2'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

### Error: `Identity Pool does not exist`

**Causa:** El pool no existe o el nombre es incorrecto.

**Solución:**
```bash
# Verificar que el pool existe
gcloud iam workload-identity-pools list \
  --project=trust-481601 \
  --location=global

# Si no existe, crearlo
gcloud iam workload-identity-pools create github-pool \
  --project=trust-481601 \
  --location=global \
  --display-name="GitHub Actions Pool"
```

### Error: `Permission iam.serviceAccounts.getAccessToken denied`

**Causa:** Falta el binding `roles/iam.serviceAccountTokenCreator`.

**Solución:**
```bash
REPO="timmd-9216/trust-engine-v2"  # Ajustar según tu repo
PROJECT_ID=trust-481601
POOL=github-pool

gcloud iam service-accounts add-iam-policy-binding ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com \
  --project=${PROJECT_ID} \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --role="roles/iam.serviceAccountTokenCreator"
```

### Error: `No credentialed accounts` en el workflow

**Causa:** WIF no está autenticando correctamente.

**Soluciones:**

1. **Verificar que el workflow tiene el permiso correcto:**
   ```yaml
   permissions:
     contents: read
     id-token: write  # ← Esto es crítico para WIF
   ```

2. **Verificar que el secret `GCP_WORKLOAD_IDENTITY_PROVIDER` está configurado:**
   - Ve a GitHub → Settings → Environments → `trust-engine`
   - Verifica que `GCP_WORKLOAD_IDENTITY_PROVIDER` existe y tiene el valor correcto

3. **Verificar que el secret `GCP_SERVICE_ACCOUNT_EMAIL` coincide exactamente:**
   - Debe ser exactamente: `ci-deployer@trust-481601.iam.gserviceaccount.com`

### Error: `Role roles/storage.objectViewer is not supported`

**Causa:** Intentaste asignar un rol no soportado directamente al service account.

**Solución:** No asignes roles de storage directamente. En su lugar, usa los roles de proyecto como se muestra en la configuración inicial.

## Terraform sketch (adjust names)
```hcl
resource "google_service_account" "ci" {
  project      = var.project_id
  account_id   = "ci-deployer"
  display_name = "CI Deployer"
}

resource "google_workload_identity_pool" "github" {
  project      = var.project_id
  location     = "global"
  workload_identity_pool_id = "github-pool"
}

resource "google_workload_identity_pool_provider" "github_oidc" {
  project                    = var.project_id
  location                   = "global"
  workload_identity_pool_id  = google_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name               = "GitHub Actions"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = {
    "google.subject"     = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }
}

resource "google_service_account_iam_member" "ci_wif_user" {
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_workload_identity_pool.github.name}/attribute.repository/OWNER/REPO"
}

resource "google_project_iam_member" "ci_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_project_iam_member" "ci_ar_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.ci.email}"
}
```
