import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    service_name: str = os.getenv("SERVICE_NAME", "scrapping-tools")
    environment: str = os.getenv("ENVIRONMENT", "local")
    version: str = "0.1.0"

    # Postgres (Neon) configuration — replaces Firestore
    database_url: str = os.getenv("DATABASE_URL", "")
    posts_table: str = os.getenv("POSTS_TABLE", "posts")
    jobs_table: str = os.getenv("JOBS_TABLE", "jobs")

    # Vercel Blob configuration — replaces GCS
    blob_read_write_token: str = os.getenv("BLOB_READ_WRITE_TOKEN", "")

    # External Information Tracer service configuration
    information_tracer_api_key: str = os.getenv("INFORMATION_TRACER_API_KEY", "")

    # API key auth for service endpoints (optional; empty = no auth, dev local)
    api_key: str = os.getenv("API_KEY", "")

    # Vercel Cron configuration
    cron_secret: str = os.getenv("CRON_SECRET", "")
    cron_max_posts: int = int(os.getenv("CRON_MAX_POSTS", "10"))
    cron_max_jobs: int = int(os.getenv("CRON_MAX_JOBS", "20"))

    # Job logging configuration
    # If True, jobs will be updated with references to execution_log_file and error_log_file
    # This increases DB write operations but improves traceability
    # Default: False (disabled) to minimize writes
    enable_job_log_references: bool = os.getenv("ENABLE_JOB_LOG_REFERENCES", "false").lower() in (
        "true",
        "1",
        "yes",
    )


settings = Settings()
