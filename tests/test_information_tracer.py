"""Tests for information_tracer module."""

from unittest.mock import MagicMock, patch

import pytest

from trust_api.scrapping_tools import information_tracer


class TestGetPostReplies:
    """Tests for get_post_replies function."""

    def test_get_post_replies_no_token(self):
        """Test that ValueError is raised when no token is provided."""
        with patch.object(information_tracer, "API_KEY", ""):
            with pytest.raises(ValueError, match="API token is required"):
                information_tracer.get_post_replies(
                    post_id="123",
                    platform="instagram",
                    max_post=100,
                    token=None,
                    start_date="2024-01-01",
                    end_date="2024-12-31",
                )

    @patch("trust_api.scrapping_tools.information_tracer.submit")
    def test_get_post_replies_submit_fails(self, mock_submit):
        """Test that ValueError is raised when submit fails."""
        mock_submit.return_value = (None, {})

        with pytest.raises(ValueError, match="Failed to submit"):
            information_tracer.get_post_replies(
                post_id="123",
                platform="instagram",
                max_post=100,
                token="test-token",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    @patch("trust_api.scrapping_tools.information_tracer.submit")
    @patch("trust_api.scrapping_tools.information_tracer.check_status")
    def test_get_post_replies_job_not_finished(self, mock_check_status, mock_submit):
        """Test that RuntimeError is raised when job doesn't finish."""
        mock_submit.return_value = ("job123", {})
        mock_check_status.return_value = ("failed", 500)

        with pytest.raises(RuntimeError, match="Job did not complete"):
            information_tracer.get_post_replies(
                post_id="123",
                platform="instagram",
                max_post=100,
                token="test-token",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    @patch("trust_api.scrapping_tools.information_tracer.submit")
    @patch("trust_api.scrapping_tools.information_tracer.check_status")
    @patch("trust_api.scrapping_tools.information_tracer.get_result")
    def test_get_post_replies_no_results(self, mock_get_result, mock_check_status, mock_submit):
        """Test that RuntimeError is raised when no results are returned."""
        mock_submit.return_value = ("job123", {})
        mock_check_status.return_value = ("finished", 200)
        mock_get_result.return_value = (None, 500)

        with pytest.raises(RuntimeError, match="Failed to retrieve results"):
            information_tracer.get_post_replies(
                post_id="123",
                platform="instagram",
                max_post=100,
                token="test-token",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    @patch("trust_api.scrapping_tools.information_tracer.submit")
    @patch("trust_api.scrapping_tools.information_tracer.check_status")
    @patch("trust_api.scrapping_tools.information_tracer.get_result")
    def test_get_post_replies_success(self, mock_get_result, mock_check_status, mock_submit):
        """Test successful reply collection returns data and job_id."""
        mock_submit.return_value = ("hash256_abc123", {"query": "reply:123"})
        mock_check_status.return_value = ("finished", 200)
        mock_get_result.return_value = (
            [
                {"reply_id": "1", "text": "Reply 1"},
                {"reply_id": "2", "text": "Reply 2"},
            ],
            200,
        )

        result = information_tracer.get_post_replies(
            post_id="123",
            platform="instagram",
            max_post=100,
            token="test-token",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Verify result structure
        assert "data" in result
        assert "job_id" in result
        assert result["job_id"] == "hash256_abc123"
        assert len(result["data"]) == 2
        assert result["data"][0]["reply_id"] == "1"

    @patch("trust_api.scrapping_tools.information_tracer.submit")
    @patch("trust_api.scrapping_tools.information_tracer.check_status")
    @patch("trust_api.scrapping_tools.information_tracer.get_result")
    def test_get_post_replies_constructs_correct_query(
        self, mock_get_result, mock_check_status, mock_submit
    ):
        """Test that correct query is constructed for reply search."""
        mock_submit.return_value = ("job123", {})
        mock_check_status.return_value = ("finished", 200)
        mock_get_result.return_value = ([], 200)

        information_tracer.get_post_replies(
            post_id="12345",
            platform="twitter",
            max_post=50,
            token="test-token",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        # Verify submit was called with correct query
        mock_submit.assert_called_once()
        call_kwargs = mock_submit.call_args[1]
        assert call_kwargs["query"] == "reply:12345"
        assert call_kwargs["platform"] == "twitter"
        assert call_kwargs["max_post"] == 50
        assert call_kwargs["timeline_only"] is False  # Must be False for reply searches
        assert call_kwargs["start_date"] == "2024-01-01"
        assert call_kwargs["end_date"] == "2024-12-31"


class TestSubmit:
    """Tests for submit function."""

    @patch("trust_api.scrapping_tools.information_tracer.requests.post")
    def test_submit_success(self, mock_post):
        """Test successful job submission."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id_hash256": "hash123"}
        mock_post.return_value = mock_response

        job_id, params = information_tracer.submit(
            token="test-token",
            query="reply:123",
            max_post=100,
            sort_by="time",
            start_date="2020-01-01",
            end_date="2025-12-31",
            platform="instagram",
            timeline_only=False,
            enable_ai=False,
        )

        assert job_id == "hash123"
        assert params is not None

    @patch("trust_api.scrapping_tools.information_tracer.requests.post")
    def test_submit_no_job_id(self, mock_post):
        """Test that None is returned when no job ID is in response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "Invalid request"}
        mock_post.return_value = mock_response

        job_id, params = information_tracer.submit(
            token="test-token",
            query="reply:123",
            max_post=100,
            sort_by="time",
            start_date="2020-01-01",
            end_date="2025-12-31",
            platform="instagram",
            timeline_only=False,
            enable_ai=False,
        )

        assert job_id is None


class TestCheckStatus:
    """Tests for check_status function."""

    @patch("trust_api.scrapping_tools.information_tracer.requests.get")
    @patch("trust_api.scrapping_tools.information_tracer.time.sleep")
    def test_check_status_finished(self, mock_sleep, mock_get):
        """Test that 'finished' is returned when job completes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "finished"}
        mock_get.return_value = mock_response

        status, code = information_tracer.check_status("job123", "test-token")

        assert status == "finished"
        assert code == 200

    @patch("trust_api.scrapping_tools.information_tracer.requests.get")
    @patch("trust_api.scrapping_tools.information_tracer.time.sleep")
    def test_check_status_polls_until_complete(self, mock_sleep, mock_get):
        """Test that check_status polls until job is complete."""
        response1 = MagicMock()
        response1.status_code = 200
        response1.json.return_value = {"status": "running"}
        response2 = MagicMock()
        response2.status_code = 200
        response2.json.return_value = {"status": "running"}
        response3 = MagicMock()
        response3.status_code = 200
        response3.json.return_value = {"status": "finished"}
        responses = [response1, response2, response3]
        mock_get.side_effect = responses

        status, code = information_tracer.check_status("job123", "test-token")

        assert status == "finished"
        assert code == 200
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2  # Sleep between polls


class TestCheckApiUsage:
    """Tests for check_api_usage function."""

    @patch("trust_api.scrapping_tools.information_tracer.requests.get")
    def test_check_api_usage(self, mock_get):
        """Test API usage check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "quota_used": 100,
            "quota_limit": 1000,
        }
        mock_get.return_value = mock_response

        result = information_tracer.check_api_usage("test-token")

        assert result["quota_used"] == 100
        assert result["quota_limit"] == 1000
