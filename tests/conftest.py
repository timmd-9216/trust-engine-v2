"""Shared pytest fixtures and configuration."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from stanza import Document

from trust_api.main import app
from trust_api.services.stanza_service import StanzaService


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    return TestClient(app)


@pytest.fixture
def mock_stanza_service():
    """Create a mock StanzaService for testing."""
    service = MagicMock(spec=StanzaService)
    service.is_initialized = True
    return service


@pytest.fixture
def mock_stanza_doc():
    """Create a mock Stanza Document for testing."""
    doc = MagicMock(spec=Document)

    # Create mock sentences with words
    sentence1 = MagicMock()
    word1 = MagicMock()
    word1.text = "El"
    word1.upos = "DET"
    word1.feats = None
    word2 = MagicMock()
    word2.text = "gobierno"
    word2.upos = "NOUN"
    word2.feats = None
    word3 = MagicMock()
    word3.text = "anunció"
    word3.upos = "VERB"
    word3.feats = "Tense=Past|Mood=Ind"
    word4 = MagicMock()
    word4.text = "nuevas"
    word4.upos = "ADJ"
    word4.feats = None
    word5 = MagicMock()
    word5.text = "medidas"
    word5.upos = "NOUN"
    word5.feats = None

    sentence1.words = [word1, word2, word3, word4, word5]

    sentence2 = MagicMock()
    word6 = MagicMock()
    word6.text = "Las"
    word6.upos = "DET"
    word6.feats = None
    word7 = MagicMock()
    word7.text = "medidas"
    word7.upos = "NOUN"
    word7.feats = None
    word8 = MagicMock()
    word8.text = "son"
    word8.upos = "VERB"
    word8.feats = "Tense=Pres|Mood=Ind"
    word9 = MagicMock()
    word9.text = "importantes"
    word9.upos = "ADJ"
    word9.feats = None

    sentence2.words = [word6, word7, word8, word9]

    doc.sentences = [sentence1, sentence2]

    return doc


@pytest.fixture
def sample_article():
    """Sample article data for testing."""
    return {
        "body": "El gobierno anunció nuevas medidas económicas. Las medidas son importantes para la economía.",
        "title": "Nuevas medidas económicas",
        "author": "Juan Pérez",
        "link": "https://example.com/article",
        "date": "2024-01-15",
        "media_type": "news",
    }


@pytest.fixture
def sample_article_long():
    """Sample long article data for testing word count."""
    body = " ".join(["Palabra"] * 600)  # 600 words
    return {
        "body": body,
        "title": "Artículo largo",
        "author": "Autor",
        "link": "https://example.com/long",
        "date": "2024-01-15",
        "media_type": "news",
    }


@pytest.fixture
def sample_article_short():
    """Sample short article data for testing."""
    return {
        "body": "Texto corto.",
        "title": "Título",
        "author": "Autor",
        "link": "https://example.com/short",
        "date": "2024-01-15",
        "media_type": "news",
    }


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    monkeypatch.setenv("STANZA_SKIP_INIT", "1")  # Skip Stanza initialization in tests
    monkeypatch.setenv("STANZA_LANG", "es")
    monkeypatch.setenv("STANZA_RESOURCES_DIR", "/tmp/stanza_resources")
    # Don't set OPENROUTER_API_KEY by default to test fallback behavior


@pytest.fixture
def mock_openrouter_api_key(monkeypatch):
    """Mock OPENROUTER_API_KEY environment variable."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-api-key")


@pytest.fixture
def mock_openrouter_response():
    """Mock successful OpenRouter API response."""
    return {"choices": [{"message": {"content": "2"}}]}
