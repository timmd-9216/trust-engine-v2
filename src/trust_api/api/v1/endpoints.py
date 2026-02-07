"""Article and corpus analysis endpoints."""

from typing import List

from fastapi import APIRouter, HTTPException, status

from trust_api.models import ArticleInput, Metric
from trust_api.nlp.models import CorpusAnalysisResult, CorpusAnalyzeRequest
from trust_api.nlp.services import run_corpus_analysis
from trust_api.services.metrics import (
    get_adjective_count,
    get_sentence_complexity,
    get_verb_tense_analysis,
    get_word_count,
)
from trust_api.services.stanza_service import stanza_service

router = APIRouter()


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=List[Metric],
    summary="Analyze article for trust and credibility",
    description="Receives article data and returns NLP-based analysis results as a list of metrics including adjective count, word count, sentence complexity, and verb tense analysis.",
    response_description="List of metrics with analysis results for different criteria",
    responses={
        200: {
            "description": "Successful analysis",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": 0,
                            "criteria_name": "Adjective Count",
                            "explanation": "Article contains a moderate number of adjectives.",
                            "flag": 0,
                            "score": 0.5,
                        },
                        {
                            "id": 1,
                            "criteria_name": "Word Count",
                            "explanation": "Article length is appropriate for the topic.",
                            "flag": 1,
                            "score": 0.8,
                        },
                    ]
                }
            },
        },
        503: {
            "description": "Service Unavailable - NLP service not initialized",
            "content": {
                "application/json": {
                    "example": {"detail": "NLP service not initialized. Please try again later."}
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"detail": "Error processing article: <error message>"}
                }
            },
        },
    },
    tags=["Analysis"],
)
async def analyze_article(article: ArticleInput) -> List[Metric]:
    """
    Analyze an article for trust and credibility.

    This endpoint receives article data and returns analysis results as a list of metrics.

    Args:
        article: ArticleInput model containing article details

    Returns:
        List of Metric objects with analysis results for different criteria
    """
    try:
        # Check if Stanza is initialized
        if not stanza_service.is_initialized:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="NLP service not initialized. Please try again later.",
            )

        # Combine title and body for full text analysis
        full_text = f"{article.title}. {article.body}"

        # Create Stanza document
        doc = stanza_service.create_doc(full_text)

        # Calculate metrics using Stanza analysis
        metrics = [
            get_adjective_count(doc, metric_id=0),
            get_word_count(doc, metric_id=1),
            get_sentence_complexity(doc, metric_id=2),
            get_verb_tense_analysis(doc, metric_id=3),
        ]

        return metrics

    except HTTPException:
        # Re-raise HTTPException as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing article: {str(e)}",
        )


@router.post(
    "/analyze-corpus",
    status_code=status.HTTP_200_OK,
    response_model=CorpusAnalysisResult,
    summary="Analyze corpus of posts (trust + NLP)",
    description=(
        "Runs full NLP corpus analysis: entity mentions, adjectives per candidate, "
        "top accounts by negative/calificative activity, account clusters, "
        "word/adjective clusters per candidate. Complements /analyze (single-article metrics)."
    ),
    response_description="Corpus analysis result with entities, adjectives, accounts, clusters",
    tags=["Analysis"],
)
async def analyze_corpus(payload: CorpusAnalyzeRequest) -> CorpusAnalysisResult:
    """
    Analyze a corpus of posts (e.g. social media) for trust and discourse metrics.

    Uses the same NLP stack as article analysis, plus NER and corpus-level aggregations.
    Posts should include at least text (full_text/text/body); optional author and candidate_id.
    """
    try:
        return run_corpus_analysis(
            posts=payload.posts,
            candidate_entities=payload.candidate_entities,
            top_negative_k=payload.top_negative_k,
            batch_size=payload.batch_size,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
