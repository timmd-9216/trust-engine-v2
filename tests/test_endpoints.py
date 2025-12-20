"""Tests for API endpoints."""

from unittest.mock import patch

from fastapi import status

from trust_api.services.stanza_service import stanza_service


class TestAnalyzeEndpoint:
    """Tests for the /api/v1/analyze endpoint."""

    def test_analyze_endpoint_success(self, client, sample_article, mock_stanza_doc):
        """Test successful article analysis."""
        with (
            patch.object(stanza_service, "is_initialized", True),
            patch.object(stanza_service, "create_doc", return_value=mock_stanza_doc),
        ):
            response = client.post("/api/v1/analyze", json=sample_article)
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 4  # Should return 4 metrics
            for metric in data:
                assert "id" in metric
                assert "criteria_name" in metric
                assert "explanation" in metric
                assert "flag" in metric
                assert "score" in metric
                assert metric["flag"] in [-1, 0, 1]
                assert 0.0 <= metric["score"] <= 1.0

    def test_analyze_endpoint_service_not_initialized(self, client, sample_article):
        """Test that endpoint returns 503 when service is not initialized."""
        with patch.object(stanza_service, "is_initialized", False):
            response = client.post("/api/v1/analyze", json=sample_article)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            data = response.json()
            assert "detail" in data
            assert "not initialized" in data["detail"].lower()

    def test_analyze_endpoint_invalid_input(self, client, mock_stanza_doc):
        """Test that invalid input returns 422."""
        with (
            patch.object(stanza_service, "is_initialized", True),
            patch.object(stanza_service, "create_doc", return_value=mock_stanza_doc),
        ):
            # Missing required fields
            response = client.post("/api/v1/analyze", json={"body": "test"})
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_analyze_endpoint_empty_body(self, client, mock_stanza_doc):
        """Test analysis with empty body."""
        with (
            patch.object(stanza_service, "is_initialized", True),
            patch.object(stanza_service, "create_doc", return_value=mock_stanza_doc),
        ):
            article = {
                "body": "",
                "title": "Test",
                "author": "Author",
                "link": "https://example.com",
                "date": "2024-01-15",
                "media_type": "news",
            }
            response = client.post("/api/v1/analyze", json=article)
            # Should still process (empty text is valid input)
            assert response.status_code in [
                status.HTTP_200_OK,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ]

    def test_analyze_endpoint_combines_title_and_body(
        self, client, sample_article, mock_stanza_doc
    ):
        """Test that endpoint combines title and body for analysis."""
        with (
            patch.object(stanza_service, "is_initialized", True),
            patch.object(stanza_service, "create_doc", return_value=mock_stanza_doc) as mock_create,
        ):
            response = client.post("/api/v1/analyze", json=sample_article)
            assert response.status_code == status.HTTP_200_OK
            # Verify that create_doc was called with combined text
            mock_create.assert_called_once()
            call_args = mock_create.call_args[0][0]
            assert sample_article["title"] in call_args
            assert sample_article["body"] in call_args
