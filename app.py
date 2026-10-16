"""Vercel Python entrypoint — exposes the scrapping-tools FastAPI app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from trust_api.scrapping_tools.main import app  # noqa: E402

__all__ = ["app"]
