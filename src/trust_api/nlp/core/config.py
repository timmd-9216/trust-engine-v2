import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    service_name: str = os.getenv("SERVICE_NAME", "nlp-process")
    environment: str = os.getenv("ENVIRONMENT", "local")
    version: str = "0.1.0"


settings = Settings()
