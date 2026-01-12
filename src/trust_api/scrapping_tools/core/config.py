import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    service_name: str = os.getenv("SERVICE_NAME", "scrapping-tools")
    environment: str = os.getenv("ENVIRONMENT", "local")
    version: str = "0.1.0"

    # Firestore configuration
    firestore_database: str = os.getenv("FIRESTORE_DATABASE", "socialnetworks")
    firestore_collection: str = os.getenv("FIRESTORE_COLLECTION", "posts")
    firestore_jobs_collection: str = os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "")

    # External Information Tracer service configuration
    information_tracer_api_key: str = os.getenv("INFORMATION_TRACER_API_KEY", "")

    # GCS configuration
    gcs_bucket_name: str = os.getenv("GCS_BUCKET_NAME", "")

    # Job logging configuration
    # If True, jobs will be updated with references to execution_log_file and error_log_file
    # This increases Firestore write operations but improves traceability
    # Default: False (disabled) to minimize Firestore writes
    enable_job_log_references: bool = os.getenv("ENABLE_JOB_LOG_REFERENCES", "false").lower() in (
        "true",
        "1",
        "yes",
    )


settings = Settings()
