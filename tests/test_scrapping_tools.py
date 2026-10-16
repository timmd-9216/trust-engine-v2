"""Tests for scrapping_tools service."""

from unittest.mock import patch

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
            max_posts_replies=50,
            job_id="abc123",
        )

        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["post_id"] == "123"
        assert entry["url"] == "https://example.com"
        assert entry["success"] is True
        assert entry["status_code"] == 200
        assert entry["response_time_ms"] == 100.5
        assert entry["max_posts_replies"] == 50
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
            skip_reason="max_posts_replies=0 (no replies expected)",
            max_posts_replies=0,
        )

        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["post_id"] == "789"
        assert entry["skipped"] is True
        assert entry["skip_reason"] == "max_posts_replies=0 (no replies expected)"
        assert entry["max_posts_replies"] == 0

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
    def test_fetch_post_information_no_dates(self, mock_settings):
        """Test that ValueError is raised when start_date or end_date are not provided."""
        mock_settings.information_tracer_api_key = "test-key"

        with pytest.raises(ValueError, match="start_date and end_date are required"):
            services.fetch_post_information(
                post_id="123",
                platform="instagram",
                max_posts_replies=100,
            )

    @patch("trust_api.scrapping_tools.services.settings")
    def test_fetch_post_information_no_api_key(self, mock_settings):
        """Test that ValueError is raised when API key is not configured."""
        mock_settings.information_tracer_api_key = ""

        with pytest.raises(ValueError, match="INFORMATION_TRACER_API_KEY is not configured"):
            services.fetch_post_information(
                post_id="123",
                platform="instagram",
                max_posts_replies=100,
                start_date="2020-01-01",
                end_date="2027-12-31",
            )

    @patch("trust_api.scrapping_tools.services.settings")
    def test_fetch_post_information_invalid_platform(self, mock_settings):
        """Test that ValueError is raised for invalid platform."""
        mock_settings.information_tracer_api_key = "test-key"

        with pytest.raises(ValueError, match="Invalid platform"):
            services.fetch_post_information(
                post_id="123",
                platform="invalid_platform",
                max_posts_replies=100,
                start_date="2020-01-01",
                end_date="2027-12-31",
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
            max_posts_replies=100,
            start_date="2020-01-01",
            end_date="2027-12-31",
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
                max_posts_replies=100,
                start_date="2020-01-01",
                end_date="2027-12-31",
            )

        # Error should be logged
        assert len(services._execution_logs) == 1
        entry = services._execution_logs[0]
        assert entry["success"] is False
        assert entry["error_message"] == "API timeout"


class TestQueryPostsWithoutReplies:
    """Tests for query_posts_without_replies function."""

    @patch("trust_api.scrapping_tools.services.db.list_posts_where")
    @patch("trust_api.scrapping_tools.services.db.list_posts")
    def test_query_posts_orders_by_created_at(self, mock_list_posts, mock_list_where):
        """Test that posts are queried ordered by created_at (twitter first)."""
        mock_list_posts.return_value = []
        mock_list_where.return_value = []

        services.query_posts_without_replies()

        mock_list_posts.assert_called_once_with("noreplies", platform="twitter")
        mock_list_where.assert_called_once_with("noreplies", not_platform="twitter", limit=None)

    @patch("trust_api.scrapping_tools.services.db.list_posts_where")
    @patch("trust_api.scrapping_tools.services.db.list_posts")
    def test_query_posts_with_limit(self, mock_list_posts, mock_list_where):
        """Test that limit is applied (twitter posts prioritized)."""
        mock_list_posts.return_value = [
            {
                "post_id": f"twitter_{i}",
                "platform": "twitter",
                "country": "argentina",
                "candidate_id": "cand1",
                "_doc_id": f"twitter_doc_{i}",
            }
            for i in range(15)  # More than max_posts=10 to test truncation
        ]
        mock_list_where.return_value = []

        result = services.query_posts_without_replies(max_posts=10)

        # Non-twitter query gets the remaining limit (0 remaining -> not called
        # only if twitter already filled the quota)
        assert len(result) == 10
        for post in result:
            assert post["platform"] == "twitter"
            assert "_doc_id" in post

    @patch("trust_api.scrapping_tools.services.db.list_posts_where")
    @patch("trust_api.scrapping_tools.services.db.list_posts")
    def test_query_posts_twitter_first_then_others(self, mock_list_posts, mock_list_where):
        """Test twitter posts come first, then other platforms fill the limit."""
        mock_list_posts.return_value = [
            {"post_id": "t1", "platform": "twitter", "_doc_id": "d1"},
        ]
        mock_list_where.return_value = [
            {"post_id": "i1", "platform": "instagram", "_doc_id": "d2"},
            {"post_id": "i2", "platform": "instagram", "_doc_id": "d3"},
        ]

        result = services.query_posts_without_replies(max_posts=3)

        assert [p["post_id"] for p in result] == ["t1", "i1", "i2"]
        mock_list_where.assert_called_once_with("noreplies", not_platform="twitter", limit=2)


class TestProcessPostsService:
    """Tests for process_posts_service function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    @patch("trust_api.scrapping_tools.services.query_posts_without_replies")
    @patch("trust_api.scrapping_tools.services.save_execution_logs")
    def test_process_posts_skips_zero_replies(self, mock_save_logs, mock_query_posts):
        """Test that posts with max_posts_replies <= 0 are skipped."""
        mock_query_posts.return_value = [
            {
                "post_id": "123",
                "platform": "instagram",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_posts_replies": 0,
                "_doc_id": "doc1",
            },
            {
                "post_id": "456",
                "platform": "instagram",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_posts_replies": -5,
                "_doc_id": "doc2",
            },
        ]
        mock_save_logs.return_value = None

        with patch("trust_api.scrapping_tools.services.update_post_status") as mock_update:
            result = services.process_posts_service(max_posts_to_process=10)

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
            assert "no replies expected" in entry["skip_reason"]

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
                "max_posts_replies": 100,
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
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

        result = services.process_posts_service(max_posts_to_process=10)

        assert result["processed"] == 1
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert len(result["jobs_created"]) == 1
        assert result["jobs_created"][0]["job_id"] == "job123"
        assert result["jobs_created"][0]["post_id"] == "123"

    @patch("trust_api.scrapping_tools.services.query_posts_without_replies")
    @patch("trust_api.scrapping_tools.services.submit_post_job")
    @patch("trust_api.scrapping_tools.services.save_pending_job")
    @patch("trust_api.scrapping_tools.services.read_from_gcs_if_exists")
    @patch("trust_api.scrapping_tools.services.has_existing_job_for_post")
    @patch("trust_api.scrapping_tools.services.save_execution_logs")
    @patch("trust_api.scrapping_tools.services.update_post_status")
    def test_process_posts_uses_max_posts_replies_fallback(
        self,
        mock_update_post_status,
        mock_save_execution_logs,
        mock_has_existing_job,
        mock_read_gcs,
        mock_save_job,
        mock_submit_job,
        mock_query_posts,
    ):
        """Test that post with max_posts_replies is used."""
        mock_query_posts.return_value = [
            {
                "post_id": "999",
                "platform": "twitter",
                "country": "argentina",
                "candidate_id": "cand1",
                "max_posts_replies": 50,
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "_doc_id": "doc99",
            },
        ]
        mock_read_gcs.return_value = None
        mock_has_existing_job.return_value = False
        mock_submit_job.return_value = "job999"
        mock_save_job.return_value = "job_doc_999"
        mock_save_execution_logs.return_value = None

        result = services.process_posts_service(max_posts_to_process=10)

        assert result["succeeded"] == 1
        mock_submit_job.assert_called_once()
        call_kwargs = mock_submit_job.call_args[1]
        assert call_kwargs["max_posts_replies"] == 50
        mock_save_job.assert_called_once()
        save_job_kwargs = mock_save_job.call_args[1]
        assert save_job_kwargs["max_posts_replies"] == 50


class TestSaveExecutionLogs:
    """Tests for save_execution_logs function."""

    def setup_method(self):
        """Reset logs before each test."""
        services.reset_execution_logs()

    @patch("trust_api.scrapping_tools.services.settings")
    def test_save_logs_no_bucket(self, mock_settings):
        """Test that None is returned when Blob token is not configured."""
        mock_settings.blob_read_write_token = ""

        services.add_log_entry(post_id="123", url="test", success=True)
        result = services.save_execution_logs()

        assert result is None

    @patch("trust_api.scrapping_tools.services.settings")
    def test_save_logs_empty_logs(self, mock_settings):
        """Test that None is returned when there are no logs."""
        mock_settings.blob_read_write_token = "test-token"

        result = services.save_execution_logs()

        assert result is None

    @patch("trust_api.scrapping_tools.services.settings")
    @patch("trust_api.scrapping_tools.services.blob.put")
    def test_save_logs_includes_statistics(self, mock_blob_put, mock_settings):
        """Test that log file includes correct statistics."""
        mock_settings.blob_read_write_token = "test-token"
        mock_blob_put.return_value = "https://store.public.blob.vercel-storage.com/logs/x.json"

        # Add some log entries
        services.add_log_entry(post_id="1", url="test", success=True, job_id="job1")
        services.add_log_entry(post_id="2", url="test", success=True, job_id="job2")
        services.add_log_entry(
            post_id="3", url="N/A", success=False, skipped=True, skip_reason="test"
        )

        result = services.save_execution_logs(requested_max_posts=10, available_posts=50)

        assert result is not None
        assert result.startswith("blob://logs/")

        # Verify blob.put was called with the log content
        mock_blob_put.assert_called_once()
        call_args = mock_blob_put.call_args
        assert call_args[0][0].startswith("logs/")
        uploaded_content = call_args[0][1]

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

    @patch("trust_api.scrapping_tools.services.db.update_post")
    def test_update_post_status_success(self, mock_update_post):
        """Test successful status update."""
        services.update_post_status("doc123", "done")

        mock_update_post.assert_called_once()
        call_args = mock_update_post.call_args
        assert call_args[0][0] == "doc123"
        fields = call_args[0][1]
        assert fields["status"] == "done"
        assert "updated_at" in fields


class TestApiKeyAuth:
    """Tests for the require_api_key dependency (X-API-Key header)."""

    def _client(self):
        from fastapi.testclient import TestClient

        from trust_api.scrapping_tools.main import app

        return TestClient(app)

    def test_protected_endpoint_without_api_key_configured(self):
        """When API_KEY is empty, protected endpoints don't require a key."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.version = "0.1.0"
            with patch("trust_api.scrapping_tools.main.query_pending_jobs", return_value=[]):
                response = self._client().get("/pending-jobs")
        assert response.status_code == 200

    def test_protected_endpoint_requires_api_key(self):
        """When API_KEY is set, requests without header return 401."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            mock_settings.version = "0.1.0"
            response = self._client().get("/pending-jobs")
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_api_key(self):
        """Requests with the right X-API-Key pass."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            mock_settings.version = "0.1.0"
            with patch("trust_api.scrapping_tools.main.query_pending_jobs", return_value=[]):
                response = self._client().get("/pending-jobs", headers={"X-API-Key": "secret-key"})
        assert response.status_code == 200

    def test_public_paths_dont_require_api_key(self):
        """Public paths are exempt even when API_KEY is set."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            mock_settings.version = "0.1.0"
            mock_settings.service_name = "scrapping-tools"
            mock_settings.environment = "test"
            client = self._client()
            assert client.get("/health").status_code == 200
            assert client.get("/").status_code == 200


class TestCronRoutes:
    """Tests for /cron/* routes (Authorization: Bearer CRON_SECRET)."""

    def _client(self):
        from fastapi.testclient import TestClient

        from trust_api.scrapping_tools.main import app

        return TestClient(app)

    def _settings_mock(self, mock_settings):
        mock_settings.cron_secret = "cron-secret"
        mock_settings.cron_max_posts = 10
        mock_settings.cron_max_jobs = 20
        mock_settings.api_key = ""
        mock_settings.version = "0.1.0"

    def test_cron_process_posts_unauthorized(self):
        """401 without Bearer token."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            self._settings_mock(mock_settings)
            response = self._client().get("/cron/process-posts")
        assert response.status_code == 401

    def test_cron_process_posts_wrong_token(self):
        """401 with wrong Bearer token."""
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            self._settings_mock(mock_settings)
            response = self._client().get(
                "/cron/process-posts",
                headers={"Authorization": "Bearer wrong"},
            )
        assert response.status_code == 401

    def test_cron_process_posts_ok(self):
        """200 with correct Bearer token; calls service with cron_max_posts."""
        results = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "jobs_created": [],
        }
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            self._settings_mock(mock_settings)
            with patch(
                "trust_api.scrapping_tools.main.process_posts_service",
                return_value=results,
            ) as mock_service:
                response = self._client().get(
                    "/cron/process-posts",
                    headers={"Authorization": "Bearer cron-secret"},
                )
        assert response.status_code == 200
        mock_service.assert_called_once_with(max_posts_to_process=10)

    def test_cron_process_jobs_ok(self):
        results = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "empty_results": 0,
            "still_pending": 0,
            "errors": [],
            "empty_result_jobs": [],
            "saved_files": [],
        }
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            self._settings_mock(mock_settings)
            with patch(
                "trust_api.scrapping_tools.main.process_pending_jobs_service",
                return_value=results,
            ) as mock_service:
                response = self._client().get(
                    "/cron/process-jobs",
                    headers={"Authorization": "Bearer cron-secret"},
                )
        assert response.status_code == 200
        mock_service.assert_called_once_with(max_jobs=20)

    def test_cron_json_to_parquet_ok(self):
        results = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
            "written_files": [],
        }
        with patch("trust_api.scrapping_tools.main.settings") as mock_settings:
            self._settings_mock(mock_settings)
            with patch(
                "trust_api.scrapping_tools.main.json_to_parquet_service",
                return_value=results,
            ) as mock_service:
                response = self._client().get(
                    "/cron/json-to-parquet",
                    headers={"Authorization": "Bearer cron-secret"},
                )
        assert response.status_code == 200
        mock_service.assert_called_once_with(skip_timestamp_filter=False)
