from fastapi import FastAPI
from pydantic import BaseModel

from trust_api.nlp.core.config import settings


class ProcessRequest(BaseModel):
    gcs_uri: str
    metadata: dict | None = None


class ProcessResponse(BaseModel):
    gcs_uri: str
    status: str
    output: dict


app = FastAPI(
    title="NLP Process Service",
    description="Processes CSV inputs referenced by GCS URI and returns structured output.",
    version=settings.version,
)


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "docs": "/docs",
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/process", response_model=ProcessResponse)
async def process_file(payload: ProcessRequest):
    # Placeholder processing: echo the input GCS URI and metadata.
    # Integrate real processing logic here (e.g., fetch CSV, run NLP, store results).
    result = {
        "gcs_uri": payload.gcs_uri,
        "metadata": payload.metadata or {},
        "message": "Processing stub - replace with real NLP pipeline.",
    }
    return ProcessResponse(
        gcs_uri=payload.gcs_uri,
        status="processed",
        output=result,
    )
