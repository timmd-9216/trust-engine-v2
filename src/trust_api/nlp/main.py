import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from trust_api.nlp.core.config import settings
from trust_api.nlp.models import CorpusAnalysisResult, CorpusAnalyzeRequest
from trust_api.nlp.services import run_corpus_analysis

logger = logging.getLogger(__name__)


class ProcessRequest(BaseModel):
    gcs_uri: str
    metadata: dict | None = None


class ProcessResponse(BaseModel):
    gcs_uri: str
    status: str
    output: dict


app = FastAPI(
    title="NLP Process Service",
    description=(
        "Processes CSV inputs referenced by GCS URI and runs corpus NLP analysis: "
        "entity mentions, adjectives per candidate, top negative accounts, "
        "account clusters, word/adjective clusters per candidate."
    ),
    version=settings.version,
)


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "docs": "/docs",
        "environment": settings.environment,
        "endpoints": {
            "analyze_corpus": "POST /analyze-corpus — análisis completo: entidades, adjetivos por candidato, cuentas negativas, clusters de cuentas, palabras por candidato. Enviar JSON con 'posts' y opcional 'candidate_entities'.",
            "process": "POST /process — procesamiento por GCS URI (stub).",
        },
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


@app.post("/analyze-corpus", response_model=CorpusAnalysisResult)
async def analyze_corpus(payload: CorpusAnalyzeRequest) -> CorpusAnalysisResult:
    """
    Run full NLP corpus analysis on a list of posts.

    Returns:
    - Entity mentions (NER) and counts
    - Adjectives associated to each entity/candidate
    - Top accounts by negative/disinformation activity
    - Clusters of related operating accounts
    - Word/adjective clusters per candidate
    """
    n_posts = len(payload.posts)
    logger.info(
        "analyze-corpus: request received, posts=%d, batch_size=%d", n_posts, payload.batch_size
    )
    print(
        f"[analyze-corpus] Request received: {n_posts} posts, batch_size={payload.batch_size}",
        flush=True,
    )
    try:
        return run_corpus_analysis(
            posts=payload.posts,
            candidate_entities=payload.candidate_entities,
            top_negative_k=payload.top_negative_k,
            batch_size=payload.batch_size,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
