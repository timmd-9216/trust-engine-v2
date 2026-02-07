"""Main FastAPI application entry point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trust_api.api.v1 import router as api_v1_router
from trust_api.services.stanza_service import stanza_service

# from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events for the FastAPI application.
    Downloads and initializes the Stanza Spanish model on startup.
    """
    if os.getenv("STANZA_SKIP_INIT") == "1":
        print("Skipping Stanza initialization (STANZA_SKIP_INIT=1).")
        yield
        return

    # Startup: Initialize Stanza Spanish model
    print("Initializing Stanza Spanish model...")
    stanza_service.initialize()
    print("Stanza model initialized successfully!")

    yield

    # Shutdown: cleanup if needed
    print("Shutting down...")


app = FastAPI(
    title="MediaParty Trust API",
    description="""
    ## Journalism Quality Analysis System

    An intelligent journalism quality analysis system that combines NLP with LLM-powered metrics
    to evaluate article credibility and objectivity, plus corpus-level analysis for social discourse.

    ### Features

    * **LLM-Powered Adjective Analysis**: Uses OpenRouter + DSPy to distinguish qualitative
      (opinionated) from descriptive (objective) adjectives
    * **Multi-Metric Evaluation**: 4 complementary metrics for comprehensive article assessment
    * **NLP Foundation**: Stanford Stanza for robust Spanish language processing
    * **Corpus / Social Analysis** (same API): Entity mentions, adjectives per candidate,
      top accounts by negative activity, account clusters, word clusters per candidate

    ### Article analysis (`/api/v1/analyze`)

    1. **Qualitative Adjectives**: Filters adjectives using LLM to identify opinion vs. objective language
    2. **Word Count**: Evaluates article length and coverage depth
    3. **Sentence Complexity**: Analyzes readability and writing sophistication
    4. **Verb Tense Analysis**: Evaluates professional news reporting style

    ### Corpus analysis (`/api/v1/analyze-corpus`)

    For batches of posts (e.g. social media): entity mention counts, adjectives associated to each
    candidate/entity, most active accounts in negative or calificative content, clusters of
    related accounts, and word/adjective clusters per candidate. Complements single-article metrics.

    ### Getting Started

    1. **Single article**: `/api/v1/analyze` — Try it out with an article body and title
    2. **Corpus of posts**: `/api/v1/analyze-corpus` — Send a list of posts with text and optional author/candidate_id
    """,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    contact={
        "name": "MediaParty Trust API",
        "url": "https://github.com/your-repo/mediaparty-trust-api",
    },
    license_info={
        "name": "License",
        "url": "https://github.com/your-repo/mediaparty-trust-api/blob/main/LICENSE",
    },
)

# # Configure CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Configure appropriately for production
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to MediaParty Trust API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Include API v1 routes
app.include_router(api_v1_router, prefix="/api/v1")
