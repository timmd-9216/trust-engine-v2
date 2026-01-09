"""Tests for scrapping_tools service."""

from unittest.mock import MagicMock, patch

import pytest

from trust_api.scrapping_tools import services


class TestAddLogEntry:
    """Tests for add_log_entry function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    def test_add_log_entry_success(self):
        """Test adding a successful log entry."""
        services.add_log_entry(
            post_id="123",
            url="https://example.com",
            success=True,
            status_code=200,
            response_time_ms=100.5,
            max_replies=50,
            job_id="abc123",
        )

        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["post_id"] == "123"
        assert entry["url"] == "https://example.com"
        assert entry["success"] is True
        assert entry["status_code"] == 200
        assert entry["response_time_ms"] == 100.5
        assert entry["max_replies"] == 50
        assert entry["job_id"] == "abc123"
        assert entry["skipped"] is False
        assert entry["skip_reason"] is None

    def test_add_log_entry_failed(self):
        """Test adding a failed log entry."""
        services.add_log_entry(
            post_id="456",
            url="https://example.com",
            success=False,
            error_message="Connection timeout",
            response_time_ms=5000.0,
        )

        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["post_id"] == "456"
        assert entry["success"] is False
        assert entry["error_message"] == "Connection timeout"

    def test_add_log_entry_skipped(self):
        """Test adding a skipped log entry."""
        services.add_log_entry(
            post_id="789",
            url="N/A",
            success=False,
            skipped=True,
            skip_reason="max_replies=0 (no replies expected)",
            max_replies=0,
        )

        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["post_id"] == "789"
        assert entry["skipped"] is True
        assert entry["skip_reason"] == "max_replies=0 (no replies expected)"
        assert entry["max_replies"] == 0

    def test_add_log_entry_with_job_id(self):
        """Test that job_id is properly logged."""
        services.add_log_entry(
            post_id="123",
            url="https://example.com",
            success=True,
            job_id="hash256_abc123def456",
        )

        entry = services._execution_logs[0]
        assert entry["job_id"] == "hash256_abc123def456"

    def test_add_log_entry_without_job_id(self):
        """Test that job_id can be None."""
        services.add_log_entry(
            post_id="123",
            url="https://example.com",
            success=True,
        )

        entry = services._execution_logs[0]
        assert entry["job_id"] is None


class TestResetExecutionLogs:
    """Tests for reset_execution_logs function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    def test_reset_clears_logs(self):
        """Test that reset_execution_logs clears all logs."""
        services.add_log_entry(post_id="123", url="https://example.com", success=True)
        services.add_log_entry(post_id="456", url="https://example.com", success=True)

        assert len(services._execution_logs) == 2

        services.reset_execution_logs()

        assert len(services._execution_logs) == 0
        # Also verify that error logs are cleared
        assert len(services._error_logs) == 0


class TestFetchPostInformation:
    """Tests for fetch_post_information function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    @patch("trust_api.scrapping_tools.services.settings")
    def test_fetch_post_information_no_api_key(self, mock_settings):
        """Test that ValueError is raised when API key is not configured."""
        mock_settings.information_tracer_api_key = ""

        with pytest.raises(ValueError, match="INFORMATION_TRACER_API_KEY is not configured"):
            services.fetch_post_information(
                post_id="123",
                platform="instagram",
                max_posts=100,
            )

    @patch("trust_api.scrapping_tools.services.settings")
    def test_fetch_post_information_invalid_platform(self, mock_settings):
        """Test that ValueError is raised for invalid platform."""
        mock_settings.information_tracer_api_key = "test-key"

        with pytest.raises(ValueError, match="Invalid platform"):
            services.fetch_post_information(
                post_id="123",
                platform="invalid_platform",
                max_posts=100,
            )

    @patch("trust_api.scrapping_tools.services.settings")
    @patch("trust_api.scrapping_tools.information_tracer.get_post_replies")
    def test_fetch_post_information_success(self, mock_get_replies, mock_settings):
        """Test successful fetch with job_id logged."""
        mock_settings.information_tracer_api_key = "test-key"
        mock_get_replies.return_value = {
            "data": [{"reply_id": "1", "text": "test reply"}],
            "job_id": "hash256_test123",
        }

        result = services.fetch_post_information(
            post_id="123",
            platform="instagram",
            max_posts=100,
        )

        # Should return just the data
        assert result == [{"reply_id": "1", "text": "test reply"}]

        # Log should include job_id
        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["success"] is True
        assert entry["job_id"] == "hash256_test123"
        assert entry["post_id"] == "123"

    @patch("trust_api.scrapping_tools.services.settings")
    @patch("trust_api.scrapping_tools.information_tracer.get_post_replies")
    def test_fetch_post_information_logs_on_error(self, mock_get_replies, mock_settings):
        """Test that errors are logged."""
        mock_settings.information_tracer_api_key = "test-key"
        mock_get_replies.side_effect = RuntimeError("API timeout")

        with pytest.raises(RuntimeError, match="API timeout"):
            services.fetch_post_information(
                post_id="123",
                platform="instagram",
                max_posts=100,
            )

        # Error should be logged
        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["success"] is False
        assert entry["error_message"] == "API timeout"


class TestQueryPostsWithoutReplies:
    """Tests for query_posts_without_replies function."""

    @patch("trust_api.scrapping_tools.services.get_firestore_client")
    def test_query_posts_orders_by_created_at(self, mock_get_client):
        """Test that query orders by created_at."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_where = MagicMock()
        mock_order_by = MagicMock()

        mock_get_client.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.where.return_value = mock_where
        mock_where.order_by.return_value = mock_order_by
        mock_order_by.stream.return_value = []

        services.query_posts_without_replies()

        # Verify order_by was called with "created_at"
        mock_where.order_by.assert_called_once_with("created_at")

    @patch("trust_api.scrapping_tools.services.get_firestore_client")
    def test_query_posts_with_limit(self, mock_get_client):
        """Test that limit is applied when max_posts is specified (applied in Python, not Firestore)."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Create separate mock collections for each query
        mock_collection_twitter = MagicMock()
        mock_collection_other = MagicMock()

        # Setup Twitter query chain
        mock_where_status_twitter = MagicMock()
        mock_where_platform = MagicMock()
        mock_order_by_twitter = MagicMock()

        mock_collection_twitter.where.return_value = mock_where_status_twitter
        mock_where_status_twitter.where.return_value = mock_where_platform
        mock_where_platform.order_by.return_value = mock_order_by_twitter

        # Create mock documents for Twitter posts (more than the limit)
        mock_twitter_docs = []
        for i in range(15):  # More than max_posts=10 to test truncation
            mock_doc = MagicMock()
            mock_doc.id = f"twitter_doc_{i}"
            mock_doc.to_dict.return_value = {
                "post_id": f"twitter_{i}",
                "platform": "twitter",
                "country": "argentina",
                "candidate_id": "cand1",
            }
            mock_twitter_docs.append(mock_doc)

        mock_order_by_twitter.stream.return_value = mock_twitter_docs

        # Setup other platforms query chain
        mock_where_other = MagicMock()
        mock_order_by_other = MagicMock()
        mock_collection_other.where.return_value = mock_where_other
        mock_where_other.order_by.return_value = mock_order_by_other
        mock_order_by_other.stream.return_value = []  # No other platform posts

        # Make collection() return different mocks on each call
        call_count = {"count": 0}

        def collection_side_effect(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                return mock_collection_twitter
            else:
                return mock_collection_other

        mock_client.collection.side_effect = collection_side_effect

        result = services.query_posts_without_replies(max_posts=10)

        # Verify that limit is applied in Python (result should have max 10 posts)
        assert len(result) == 10
        # Verify all returned posts are from Twitter
        for post in result:
            assert post["platform"] == "twitter"
            assert "_doc_id" in post


class TestProcessPostsService:
    """Tests for process_posts_service function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    @patch("trust_api.scrapping_tools.services.query_posts_without_replies")
    @patch("trust_api.scrapping_tools.services.save_execution_logs")
    def test_process_posts_skips_zero_replies(self, mock_save_logs, mock_query_posts):
        """Test that posts with max_replies <= 0 are skipped."""
        mock_query_posts.return_value = [
            {
                "post_id": "123",
                "platform": "instagram",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_replies": 0,
                "_doc_id": "doc1",
            },
            {
                "post_id": "456",
                "platform": "instagram",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_replies": -5,
                "_doc_id": "doc2",
            },
        ]
        mock_save_logs.return_value = None

        with patch("trust_api.scrapping_tools.services.update_post_status") as mock_update:
            result = services.process_posts_service(max_posts=10)

        assert result["processed"] == 2
        assert result["skipped"] == 2
        assert result["succeeded"] == 0
        assert result["failed"] == 0

        # Verify posts were updated to "skipped" status
        assert mock_update.call_count == 2
        mock_update.assert_any_call("doc1", "skipped")
        mock_update.assert_any_call("doc2", "skipped")

        # Verify log entries were created for skipped posts
        assert len(services._execution_logs) == 2
        for entry in services._execution_logs:
            assert entry["skipped"] is True
            assert "max_replies" in entry["skip_reason"]

    @patch("trust_api.scrapping_tools.services.query_posts_without_replies")
    @patch("trust_api.scrapping_tools.services.submit_post_job")
    @patch("trust_api.scrapping_tools.services.save_pending_job")
    @patch("trust_api.scrapping_tools.services.read_from_gcs_if_exists")
    @patch("trust_api.scrapping_tools.services.has_existing_job_for_post")
    @patch("trust_api.scrapping_tools.services.save_execution_logs")
    @patch("trust_api.scrapping_tools.services.update_post_status")
    def test_process_posts_success(
        self,
        mock_update_post_status,
        mock_save_execution_logs,
        mock_has_existing_job,
        mock_read_gcs,
        mock_save_job,
        mock_submit_job,
        mock_query_posts,
    ):
        """Test successful processing of posts."""
        mock_query_posts.return_value = [
            {
                "post_id": "123",
                "platform": "instagram",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_replies": 100,
                "_doc_id": "doc1",
            },
        ]
        # File doesn't exist in GCS, so we need to create a job
        mock_read_gcs.return_value = None
        # No existing job for this post
        mock_has_existing_job.return_value = False
        mock_submit_job.return_value = "job123"
        mock_save_job.return_value = "job_doc_id_123"
        mock_save_execution_logs.return_value = None

        result = services.process_posts_service(max_posts=10)

        assert result["processed"] == 1
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert len(result["jobs_created"]) == 1
        assert result["jobs_created"][0]["job_id"] == "job123"
        assert result["jobs_created"][0]["post_id"] == "123"


class TestSaveExecutionLogs:
    """Tests for save_execution_logs function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    @patch("trust_api.scrapping_tools.services.settings")
    def test_save_logs_no_bucket(self, mock_settings):
        """Test that None is returned when bucket is not configured."""
        mock_settings.gcs_bucket_name = ""

        services.add_log_entry(post_id="123", url="test", success=True)
        result = services.save_execution_logs()

        assert result is None

    @patch("trust_api.scrapping_tools.services.settings")
    def test_save_logs_empty_logs(self, mock_settings):
        """Test that None is returned when there are no logs."""
        mock_settings.gcs_bucket_name = "test-bucket"

        result = services.save_execution_logs()

        assert result is None

    @patch("trust_api.scrapping_tools.services.settings")
    @patch("trust_api.scrapping_tools.services.get_gcs_client")
    def test_save_logs_includes_statistics(self, mock_get_client, mock_settings):
        """Test that log file includes correct statistics."""
        mock_settings.gcs_bucket_name = "test-bucket"

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        # Add some log entries
        services.add_log_entry(post_id="1", url="test", success=True, job_id="job1")
        services.add_log_entry(post_id="2", url="test", success=True, job_id="job2")
        services.add_log_entry(
            post_id="3", url="N/A", success=False, skipped=True, skip_reason="test"
        )

        result = services.save_execution_logs(requested_max_posts=10, available_posts=50)

        assert result is not None
        assert "gs://test-bucket/logs/" in result

        # Verify blob.upload_from_string was called
        mock_blob.upload_from_string.assert_called_once()
        call_args = mock_blob.upload_from_string.call_args
        uploaded_content = call_args[0][0]

        # Parse and verify content
        import json

        log_data = json.loads(uploaded_content)
        assert log_data["requested_max_posts"] == 10
        assert log_data["available_posts"] == 50
        assert log_data["total_entries"] == 3
        assert log_data["api_calls"] == 2  # 2 non-skipped
        assert log_data["skipped_posts"] == 1


class TestUpdatePostStatus:
    """Tests for update_post_status function."""

    def test_update_post_status_no_doc_id(self):
        """Test that ValueError is raised when doc_id is empty."""
        with pytest.raises(ValueError, match="doc_id is required"):
            services.update_post_status("")

    @patch("trust_api.scrapping_tools.services.get_firestore_client")
    def test_update_post_status_success(self, mock_get_client):
        """Test successful status update."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_doc_ref = MagicMock()

        mock_get_client.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc_ref

        services.update_post_status("doc123", "done")

        mock_doc_ref.update.assert_called_once()
        call_args = mock_doc_ref.update.call_args[0][0]
        assert call_args["status"] == "done"
        assert "updated_at" in call_args
