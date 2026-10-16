"""Integration tests for scrapping_tools db.py against a real Postgres.

Run with:
    TEST_DATABASE_URL=postgresql://postgres:pg@localhost:55432/postgres \
        pytest tests/test_db_integration.py
"""

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture(scope="module")
def db():
    """db module pointed at the test database."""
    from trust_api.scrapping_tools import db as db_module
    from trust_api.scrapping_tools.core.config import settings

    settings.database_url = os.environ["TEST_DATABASE_URL"]
    return db_module


@pytest.fixture(autouse=True)
def clean_tables(db):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM posts")
    yield


class TestJobsRoundTrip:
    def test_insert_and_get_job_with_extra_fields(self, db):
        fields = {
            "job_id": "hash_abc",
            "post_doc_id": "post-doc-1",
            "post_id": "post-1",
            "platform": "twitter",
            "country": "honduras",
            "candidate_id": "cand1",
            "status": "pending",
            "max_posts_replies": 100,
            "sort_by": "time",
            # non-column fields -> extra JSONB
            "custom_field": "custom_value",
            "nested": {"a": 1},
        }
        doc_id = db.insert_job(fields)
        assert doc_id

        job = db.get_job(doc_id)
        assert job is not None
        assert job["_doc_id"] == doc_id
        assert job["job_id"] == "hash_abc"
        assert job["status"] == "pending"
        assert job["custom_field"] == "custom_value"
        assert job["nested"] == {"a": 1}
        assert "_doc_id" not in (job.get("extra") or {})

    def test_insert_with_explicit_id_upserts(self, db):
        fields = {
            "id": "firestore-doc-123",
            "job_id": "j1",
            "post_id": "p1",
            "status": "pending",
        }
        doc_id = db.insert_job(fields)
        assert doc_id == "firestore-doc-123"

        db.insert_job({**fields, "status": "done"})
        job = db.get_job("firestore-doc-123")
        assert job["status"] == "done"


class TestListPosts:
    def _insert_posts(self, db):
        for i, (platform, created) in enumerate(
            [
                ("twitter", datetime(2025, 1, 3, tzinfo=timezone.utc)),
                ("instagram", datetime(2025, 1, 1, tzinfo=timezone.utc)),
                ("twitter", datetime(2025, 1, 2, tzinfo=timezone.utc)),
            ]
        ):
            db.insert_post(
                {
                    "post_id": f"p{i}",
                    "platform": platform,
                    "country": "honduras",
                    "candidate_id": "cand1",
                    "status": "noreplies",
                    "created_at": created,
                }
            )

    def test_list_posts_filters_status_and_platform(self, db):
        self._insert_posts(db)
        posts = db.list_posts("noreplies", platform="twitter")
        assert len(posts) == 2
        assert all(p["platform"] == "twitter" for p in posts)
        # Ordered by created_at ascending
        assert posts[0]["post_id"] == "p2"  # created 2025-01-02
        assert posts[1]["post_id"] == "p0"  # created 2025-01-03

    def test_list_posts_limit(self, db):
        self._insert_posts(db)
        posts = db.list_posts("noreplies", limit=2)
        assert len(posts) == 2

    def test_list_posts_where_not_platform(self, db):
        self._insert_posts(db)
        posts = db.list_posts_where("noreplies", not_platform="twitter")
        assert len(posts) == 1
        assert posts[0]["platform"] == "instagram"

    def test_invalid_order_by_raises(self, db):
        with pytest.raises(ValueError):
            db.list_posts("noreplies", order_by="post_id")


class TestUpdatePost:
    def test_update_merges_extra_and_sets_updated_at(self, db):
        doc_id = db.insert_post(
            {
                "post_id": "p1",
                "platform": "twitter",
                "country": "honduras",
                "candidate_id": "cand1",
                "status": "noreplies",
                "note": "original",
            }
        )
        db.update_post(doc_id, {"status": "done", "note": "updated", "new_field": 7})

        post = db.get_post(doc_id)
        assert post["status"] == "done"
        assert post["note"] == "updated"
        assert post["new_field"] == 7
        assert isinstance(post["updated_at"], datetime)


class TestCountAndExists:
    def test_count_jobs_with_filters(self, db):
        for i, platform in enumerate(["twitter", "twitter", "instagram"]):
            db.insert_job(
                {
                    "job_id": f"j{i}",
                    "post_id": f"p{i}",
                    "platform": platform,
                    "country": "honduras",
                    "candidate_id": "cand1" if i < 2 else "cand2",
                    "status": "pending",
                }
            )
        db.insert_job({"job_id": "jx", "post_id": "px", "platform": "twitter", "status": "done"})

        assert db.count_jobs("pending") == 3
        assert db.count_jobs("pending", platform="twitter") == 2
        assert db.count_jobs("pending", candidate_id="cand2") == 1
        assert db.count_jobs("done") == 1

    def test_job_exists(self, db):
        db.insert_job({"job_id": "j1", "post_id": "p1", "status": "pending"})
        assert db.job_exists("p1", "pending") is True
        assert db.job_exists("p1", "processing") is False
        assert db.job_exists("other", "pending") is False
