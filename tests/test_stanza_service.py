"""Tests for StanzaService."""

from unittest.mock import MagicMock, patch

import pytest

from trust_api.services.stanza_service import StanzaService


class TestStanzaService:
    """Tests for StanzaService class."""

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = StanzaService()
        assert service._nlp is None
        assert not service.is_initialized

    def test_service_initialize(self, monkeypatch, tmp_path):
        """Test that initialize method sets up the model."""
        service = StanzaService()
        resources_dir = str(tmp_path / "stanza_resources")
        monkeypatch.setenv("STANZA_RESOURCES_DIR", resources_dir)
        monkeypatch.setenv("STANZA_LANG", "es")

        with patch("stanza.download") as mock_download, patch("stanza.Pipeline") as mock_pipeline:
            mock_pipeline_instance = MagicMock()
            mock_pipeline.return_value = mock_pipeline_instance

            service.initialize()

            mock_download.assert_called_once()
            mock_pipeline.assert_called_once()
            assert service._nlp is not None
            assert service.is_initialized

    def test_create_doc_success(self, mock_stanza_doc):
        """Test creating a document when service is initialized."""
        service = StanzaService()
        service._nlp = MagicMock()
        service._nlp.return_value = mock_stanza_doc

        doc = service.create_doc("Test text")
        assert doc == mock_stanza_doc
        service._nlp.assert_called_once_with("Test text")

    def test_create_doc_not_initialized(self):
        """Test that create_doc raises RuntimeError when not initialized."""
        service = StanzaService()
        assert service._nlp is None

        with pytest.raises(RuntimeError, match="not initialized"):
            service.create_doc("Test text")

    def test_is_initialized_property(self):
        """Test the is_initialized property."""
        service = StanzaService()
        assert not service.is_initialized

        service._nlp = MagicMock()
        assert service.is_initialized

        service._nlp = None
        assert not service.is_initialized

    def test_initialize_uses_env_vars(self, monkeypatch, tmp_path):
        """Test that initialize uses environment variables."""
        service = StanzaService()
        custom_dir = str(tmp_path / "custom_resources")
        monkeypatch.setenv("STANZA_RESOURCES_DIR", custom_dir)
        monkeypatch.setenv("STANZA_LANG", "es")

        with patch("stanza.download"), patch("stanza.Pipeline") as mock_pipeline:
            service.initialize()

            # Verify that environment variables were used
            call_kwargs = mock_pipeline.call_args[1]
            assert call_kwargs["dir"] == custom_dir
            assert call_kwargs["lang"] == "es"
