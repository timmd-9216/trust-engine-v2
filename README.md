# Trust Engine v2

**An intelligent journalism quality analysis API that combines NLP with LLM-powered metrics to evaluate article credibility and objectivity.**

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [Deployment](#-deployment)
- [Configuration](#-configuration)
- [Development](#-development)
- [Metrics](#-metrics)
- [Troubleshooting](#-troubleshooting)

---

## 🎯 Overview

Trust Engine v2 is a REST API that analyzes journalistic articles using Natural Language Processing (NLP) and Large Language Models (LLMs) to provide objective quality metrics. The system evaluates articles across multiple dimensions to help identify bias, sensationalism, and poor writing quality.

### Use Cases

- **Fact-checkers**: Identify potentially biased language in articles
- **Journalists**: Self-audit writing for objectivity
- **Media Literacy**: Teach critical reading skills with objective metrics
- **Research**: Analyze large corpora for language patterns

### How It Works

1. Submit article content via REST API
2. Stanford Stanza performs linguistic analysis (POS tagging, dependency parsing)
3. OpenRouter + DSPy filters subjective language patterns
4. Return comprehensive quality metrics

---

## ✨ Features

- **LLM-Powered Analysis**: Uses OpenRouter + DSPy to distinguish qualitative (opinionated) from descriptive (objective) adjectives
- **Multi-Metric Evaluation**: 4 complementary metrics for comprehensive assessment
- **Spanish Language Support**: Built on Stanford Stanza for robust Spanish NLP
- **REST API**: FastAPI-based with automatic OpenAPI/Swagger documentation
- **Docker Support**: Containerized for easy deployment
- **Cloud Run Ready**: Automated deployment to Google Cloud Platform
- **Auto-scaling**: Scales to zero when not in use
- **Comprehensive Logging**: Track API calls and metric calculations

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- pip or conda
- (Optional) Docker for containerized deployment
- (Optional) OpenRouter API key for LLM-powered adjective filtering

### Installation

1. **Clone the repository**
   ```bash
   cd trust-engine-v2
   ```

2. **Set up Python 3.12 with pyenv**
   ```bash
   pyenv install 3.12.7    # skip if already installed
   pyenv local 3.12.7      # uses .python-version
   ```

3. **Install Poetry and project dependencies**
   ```bash
   pip install poetry     # or pip install --user poetry
   poetry env use $(pyenv which python)
   poetry install
   ```

4. **Configure environment variables**
   ```bash
   # Copy the example file
   cp .env.example .env

   # Edit .env with your credentials
   nano .env
   ```

   Minimum configuration:
   ```bash
   # Optional but recommended for full functionality
   OPENROUTER_API_KEY=your_api_key_here
   ```

5. **Start the API server**
   ```bash
   poetry run pre-commit install  # optional: install ruff hooks locally
   poetry run uvicorn trust_api.main:app --reload
   ```

6. **Access the API**
   ```bash
   open http://localhost:8000  # or curl the endpoints below
   ```

   - API: http://localhost:8000
   - Interactive Docs: http://localhost:8000/docs
   - Alternative Docs: http://localhost:8000/redoc

---

## 📖 API Documentation

### Base URL

- **Local**: `http://localhost:8000`
- **Production**: `https://your-service-name.run.app`

### Endpoints

#### `GET /`
Root endpoint with API information.

**Response:**
```json
{
  "message": "Welcome to MediaParty Trust API",
  "version": "0.1.0",
  "docs": "/docs"
}
```

#### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy"
}
```

#### `POST /api/v1/analyze`
Analyzes a journalistic article and returns trust metrics.

**Request Body:**
```json
{
  "body": "Article content goes here...",
  "title": "Article Title",
  "author": "Author Name",
  "link": "https://example.com/article",
  "date": "2024-03-15",
  "media_type": "news"
}
```

**Response:**
```json
[
  {
    "id": 0,
    "criteria_name": "Qualitative Adjectives",
    "explanation": "The qualitative adjective ratio (3.2%) is excellent, indicating objective writing.",
    "flag": 1,
    "score": 0.9
  },
  {
    "id": 1,
    "criteria_name": "Word Count",
    "explanation": "The article has 450 words, indicating adequate coverage.",
    "flag": 0,
    "score": 0.6
  },
  {
    "id": 2,
    "criteria_name": "Sentence Complexity",
    "explanation": "Average sentence length is 18 words, indicating good readability.",
    "flag": 1,
    "score": 0.8
  },
  {
    "id": 3,
    "criteria_name": "Verb Tense Analysis",
    "explanation": "Past tense usage (55%) is appropriate for news reporting.",
    "flag": 1,
    "score": 0.75
  }
]
```

**Flag Values:**
- `1`: Positive indicator (good quality)
- `0`: Neutral (acceptable)
- `-1`: Negative indicator (poor quality)

**Score Range:** `0.0` to `1.0` (higher is better)

### Using the Interactive Documentation

1. Navigate to http://localhost:8000/docs
2. Click on the `/api/v1/analyze` endpoint
3. Click "Try it out"
4. Use the pre-filled example or modify the JSON
5. Click "Execute"
6. View the response below

### Example using cURL

```bash
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "body": "El gobierno anunció hoy nuevas medidas económicas. Las decisiones fueron tomadas después de semanas de análisis. Los expertos consideran que estas políticas tendrán un impacto significativo en la economía nacional.",
    "title": "Nuevas medidas económicas anunciadas",
    "author": "María García",
    "link": "https://example.com/article",
    "date": "2024-03-15",
    "media_type": "news"
  }'
```

### Example using Python

```python
import requests
import json

url = "http://localhost:8000/api/v1/analyze"

article = {
    "body": "El gobierno anunció hoy nuevas medidas económicas...",
    "title": "Nuevas medidas económicas anunciadas",
    "author": "María García",
    "link": "https://example.com/article",
    "date": "2024-03-15",
    "media_type": "news"
}

response = requests.post(url, json=article)
metrics = response.json()

for metric in metrics:
    print(f"{metric['criteria_name']}: {metric['score']:.2f}")
    print(f"  {metric['explanation']}")
    print()
```

---

## 🧠 NLP Process Service

A lightweight FastAPI service to receive CSV references (GCS URIs) and trigger NLP processing (stubbed; replace with real logic).

- Run locally:
  ```bash
  poetry run uvicorn trust_api.nlp.main:app --reload
  ```
- Env vars:
  - `SERVICE_NAME` (default `nlp-process`)
  - `ENVIRONMENT` (default `local`)
- Deploy via CI: set `GCP_NLP_SERVICE_NAME` in GitHub secrets/vars. The workflow reuses the same image and sets `APP_MODULE=trust_api.nlp.main:app` for the Cloud Run service.

Endpoints:
- `GET /` metadata
- `GET /health` health check
- `POST /process` with body `{"gcs_uri": "...", "metadata": {...}}` (returns a stub response)

---

## 🚢 Deployment

### Docker Deployment

1. **Build the Docker image**
   ```bash
   docker build -t trust-engine-v2 .
   ```

2. **Run the container**
   ```bash
   docker run -p 8080:8080 \
     -e OPENROUTER_API_KEY=your_key_here \
     trust-engine-v2
   ```

3. **Test the deployment**
   ```bash
   curl http://localhost:8080/health
   ```

### Google Cloud Run Deployment

This project includes automated deployment to Google Cloud Run via GitHub Actions.

#### Prerequisites

1. **Create GCP Project**
   - Go to [console.cloud.google.com](https://console.cloud.google.com)
   - Create a new project or select existing one

2. **Enable Required APIs**
   ```bash
   gcloud services enable run.googleapis.com
   gcloud services enable artifactregistry.googleapis.com
   gcloud services enable cloudbuild.googleapis.com
   ```

3. **Create Artifact Registry**
   ```bash
   gcloud artifacts repositories create cloud-run-source-deploy \
     --repository-format=docker \
     --location=us-central1 \
     --description="Docker repository for Cloud Run"
   ```

4. **Create Service Account**
   - Go to IAM & Admin → Service Accounts
   - Create service account with these roles:
     - Cloud Run Admin
     - Storage Admin
     - Artifact Registry Administrator

5. **Autenticación**
   - Uso interactivo (CLI): `gcloud auth login`
   - Credenciales por defecto (ADC) para SDK/contenedores: `gcloud auth application-default login`
   - Para CI/CD (GitHub Actions), usa Workload Identity Federation (ver secretos abajo)

6. **Setup GitHub Secrets**

   Go to your GitHub repository → Settings → Secrets and variables → Actions

   Add these secrets:
   - `GCP_PROJECT_ID`: Your GCP project ID
   - `GCP_REGION`: Deployment region (e.g., `us-central1`)
   - `GCP_SERVICE_NAME`: Service name (e.g., `trust-engine-v2`)
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`: Workload Identity Provider resource name (e.g., `projects/…/locations/global/workloadIdentityPools/…/providers/…`)
   - `GCP_SERVICE_ACCOUNT_EMAIL`: Service account email to impersonate via WIF
   - `OPENROUTER_API_KEY`: Your OpenRouter API key
   The GitHub Actions workflow authenticates via Workload Identity Federation (no JSON key required).

#### Deploy

**Automatic Deployment:**
Push to the `main` branch triggers automatic deployment.

**Manual Deployment:**
1. Go to GitHub → Actions
2. Select "Deploy to Cloud Run"
3. Click "Run workflow"

The deployment process:
1. Builds Docker container
2. Pushes to Google Artifact Registry
3. Deploys to Cloud Run
4. Runs health check
5. Outputs service URL

**Manual Cloud Build + Deploy (no local Docker)**
```bash
export GCP_PROJECT_ID=your-project
export GCP_REGION=us-central1
export GCP_SERVICE_NAME=trust-engine-v2
# Optional: overrides
export TAG=$(git rev-parse --short HEAD)            # image tag; defaults to git SHA or timestamp
export AR_REPO=cloud-run-source-deploy             # Artifact Registry repo name
export OPENROUTER_API_KEY=your_api_key             # forwarded to Cloud Run if set
export CLOUD_RUN_ENV_VARS="EXAMPLE=1,FOO=bar"      # extra env vars for Cloud Run

./scripts/deploy_cloud_run.sh
```
This uses `gcloud builds submit` to build in Cloud Build and deploys the built image to Cloud Run. The script will also create the Artifact Registry repo if it does not exist (`AR_REPO` in `GCP_REGION`).
Notes:
- The image pre-downloads the Stanza model during build (uses `STANZA_RESOURCES_DIR=/app/stanza_resources` and `STANZA_LANG`, default `es`). Runtime also passes these env vars so the model path is reused (avoids downloading on startup).
- Local dev defaults `STANZA_RESOURCES_DIR` to `./stanza_resources` (override via env if needed).

#### Access Your Deployment

After deployment, your API will be available at:
```
https://[SERVICE-NAME]-[HASH]-[REGION].a.run.app
```

Check GitHub Actions logs for the exact URL.

#### Run the remote service through a local proxy

Use `gcloud run services proxy` to bind your Cloud Run service to a local port (requires `gcloud auth login` and the correct project/region):
```bash
gcloud run services proxy $GCP_SERVICE_NAME \
  --project $GCP_PROJECT_ID \
  --region $GCP_REGION \
  --port 8080
```
Then call it via `http://localhost:8080` (e.g., `http://localhost:8080/health` or the API endpoints). Stop with Ctrl+C when finished.

You can also use the helper script (loads env vars from your shell):
```bash
source .env   # ensure GCP_PROJECT_ID, GCP_REGION, GCP_SERVICE_NAME are set
./scripts/proxy_cloud_run.sh
```

#### Cloud Run Configuration

Default settings (configurable in `.github/workflows/deploy-cloud-run.yml`):
- **Memory**: 2GB
- **CPU**: 2 vCPU
- **Timeout**: 300 seconds
- **Max instances**: 10
- **Min instances**: 0 (scales to zero)
- **Port**: 8080
- **Authentication**: Public (allow unauthenticated)

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# OpenRouter API Configuration (optional but recommended)
OPENROUTER_API_KEY=your_api_key_here

# Google Cloud Platform Configuration (for deployment)
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
GCP_SERVICE_NAME=trust-engine-v2
GCP_WORKLOAD_IDENTITY_PROVIDER=projects/.../locations/global/workloadIdentityPools/.../providers/...
GCP_SERVICE_ACCOUNT_EMAIL=sa-name@your-gcp-project-id.iam.gserviceaccount.com
```

### Getting an OpenRouter API Key

1. Sign up at [openrouter.ai](https://openrouter.ai/)
2. Go to [API Keys](https://openrouter.ai/keys)
3. Create a new API key
4. Copy to your `.env` file

**Note**: Without `OPENROUTER_API_KEY`, the adjective metric will work using all adjectives instead of filtering for qualitative ones only.

---

## 🛠️ Development

### Project Structure

```
trust-engine-v2/
├── src/trust_api/
│   ├── main.py                  # FastAPI application entry point
│   ├── models.py                # Pydantic models
│   ├── __init__.py
│   ├── nlp/                     # NLP processing service (trust-api-nlp)
│   │   ├── __init__.py
│   │   ├── main.py              # NLP service entry point
│   │   └── core/
│   │       └── config.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── endpoints.py     # API endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── metrics.py           # Metric calculation logic
│   │   └── stanza_service.py    # NLP processing service
│   └── core/
│       ├── __init__.py
│       └── config.py            # Configuration management
├── .github/
│   └── workflows/
│       └── deploy-cloud-run.yml # CI/CD pipeline
├── test/                        # Test examples
├── Dockerfile                   # Container definition
├── .dockerignore               # Docker build exclusions
├── pyproject.toml              # Python dependencies
├── .pre-commit-config.yaml     # Lint/format hooks (ruff)
├── .env.example                # Environment template
├── .gitignore                  # Git exclusions
└── README.md                   # This file
```

### Adding New Metrics

1. Open `src/trust_api/services/metrics.py`
2. Create a new function following this pattern:

```python
def get_new_metric(doc: Document, metric_id: int) -> Metric:
    """
    Calculate your new metric.

    Args:
        doc: Stanza Document object
        metric_id: Unique metric identifier

    Returns:
        Metric object with results
    """
    # Your analysis logic here
    score = 0.0  # Calculate score (0.0 to 1.0)
    flag = 0     # -1, 0, or 1

    return Metric(
        id=metric_id,
        criteria_name="Your Metric Name",
        explanation="Description of the result",
        flag=flag,
        score=score,
    )
```

3. Add to the analysis pipeline in `src/trust_api/api/v1/endpoints.py`:

```python
metrics = [
    get_adjective_count(doc, metric_id=0),
    get_word_count(doc, metric_id=1),
    get_sentence_complexity(doc, metric_id=2),
    get_verb_tense_analysis(doc, metric_id=3),
    get_new_metric(doc, metric_id=4),  # Add your metric
]
```

### Running Tests

```bash
# Run with default example
python test_api.py

# Use specific input file
python test_api.py --input test/input_example.json

# Specify output file
python test_api.py --output results.json
```

---

## 📊 Metrics

### 1. Qualitative Adjectives (LLM-Enhanced)

**What it measures**: Proportion of opinion-based adjectives vs. descriptive adjectives

**Why it matters**: Excessive qualitative adjectives signal bias or sensationalism

**How it works**:
- Extracts all adjectives using Stanza
- Uses OpenRouter + DSPy to classify as qualitative vs. descriptive
- Calculates ratio of qualitative adjectives

**Scoring**:
- ≤5%: Excellent (flag: 1, score: 0.8-1.0)
- 5-10%: Moderate (flag: 0, score: 0.5-0.8)
- >10%: High (flag: -1, score: 0.0-0.5)

### 2. Word Count

**What it measures**: Total article length

**Why it matters**: Longer articles tend to provide more comprehensive coverage

**How it works**:
- Counts all words in title + body
- Evaluates against journalistic standards

**Scoring**:
- >400 words: Good depth (flag: 1)
- 200-400 words: Moderate (flag: 0)
- <200 words: Insufficient (flag: -1)

### 3. Sentence Complexity

**What it measures**: Average sentence length

**Why it matters**: Proper complexity ensures readability without oversimplification

**How it works**:
- Calculates average words per sentence
- Optimal range: 15-25 words

**Scoring**:
- 15-25 words: Optimal (flag: 1, score: 0.8-1.0)
- 10-30 words: Acceptable (flag: 0, score: 0.5-0.8)
- Other: Poor (flag: -1, score: 0.0-0.5)

### 4. Verb Tense Analysis

**What it measures**: Distribution of verb tenses

**Why it matters**: News articles should primarily use past tense for reported events

**How it works**:
- Analyzes verb tense distribution using Stanza
- Expected for news: 40-70% past tense

**Scoring**:
- 40-70% past tense: Appropriate (flag: 1)
- 30-40% or 70-80%: Moderate (flag: 0)
- Other: Inappropriate (flag: -1)

---

## 🐛 Troubleshooting

### Error: "NLP service not initialized"

**Cause**: Stanza is downloading language models on first run

**Solution**: Wait for initialization to complete. Check server logs for progress.

```bash
# Check logs
tail -f /var/log/app.log
```

### Error: "OPENROUTER_API_KEY not set"

**Cause**: Environment variable not configured

**Solution**: The API will work with reduced functionality (all adjectives instead of filtered qualitative ones). To enable full functionality:

```bash
# Add to .env file
OPENROUTER_API_KEY=your_key_here
```

### Error: Docker build fails

**Cause**: Usually dependency or network issues

**Solution**:
```bash
# Clear Docker cache and rebuild
docker build --no-cache -t trust-engine-v2 .
```

### Error: Cloud Run deployment fails

**Cause**: Missing permissions or incorrect configuration

**Solution**: Verify:
- GitHub secrets are set correctly
- Service account has required roles
- APIs are enabled in GCP
- Artifact Registry exists

```bash
# Check service account permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:YOUR_SA_EMAIL"
```

### Performance: Slow first request

**Cause**: Stanza model loading + container cold start

**Solution**:
- First request may take 30-60 seconds
- Subsequent requests are fast (<2 seconds)
- In Cloud Run, set `min-instances: 1` to avoid cold starts

```bash
# Update Cloud Run to keep 1 instance warm
gcloud run services update trust-engine-v2 \
  --min-instances 1 \
  --region us-central1
```

---

## 📄 License

[Specify your license here]

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## 📞 Support

For issues and questions:
- GitHub Issues: [Create an issue](../../issues)
- Documentation: http://localhost:8000/docs

---

## 🏆 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Stanford Stanza](https://stanfordnlp.github.io/stanza/) - NLP toolkit
- [DSPy](https://github.com/stanfordnlp/dspy) - Programming with foundation models
- [OpenRouter](https://openrouter.ai/) - LLM API gateway
