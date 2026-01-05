"""read_data.py

Utilities to load project inputs:
- Google Sheet tabs (public or authenticated via service account).
- Local CSV/JSON inputs.

Primary use-case for this project: read the `Honduras` sheet from a Google
Spreadsheet and return it as a pandas DataFrame.

Notes
-----
* If the Google Sheet is shared as "Anyone with the link can view", the public
  CSV export endpoints will work with no credentials.
* If it is not public, you must either export the sheet manually (CSV/XLSX)
  or use a Google service account (see `--google-creds-json`).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from typing import Iterable

import pandas as pd


try:
    import requests  # type: ignore
except Exception as e:  # pragma: no cover
    requests = None


@dataclass(frozen=True)
class GoogleSheetRef:
    spreadsheet_id: str
    sheet_name: str


def _ensure_requests() -> None:
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required to fetch Google Sheets. "
            "Install it with: pip install requests"
        )


def build_public_csv_url(ref: GoogleSheetRef) -> str:
    """Build a public CSV export URL using sheet name.

    This works when the spreadsheet is shared publicly (anyone-with-link view).
    """
    # Using the 'gviz' endpoint avoids needing gid.
    # Example:
    # https://docs.google.com/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&sheet=Honduras
    return (
        f"https://docs.google.com/spreadsheets/d/{ref.spreadsheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={ref.sheet_name}"
    )


def read_google_sheet_public_csv(ref: GoogleSheetRef, *, timeout_s: int = 30) -> pd.DataFrame:
    """Read a Google Sheet tab via the public CSV export endpoint."""
    _ensure_requests()

    url = build_public_csv_url(ref)
    resp = requests.get(url, timeout=timeout_s)

    # When not public, Google often returns HTML (login / permission page).
    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch sheet CSV: HTTP {resp.status_code} for {url}")

    if "text/csv" not in content_type and "application/vnd.ms-excel" not in content_type:
        # Heuristic: if it looks like HTML, it's probably a permissions wall.
        text_head = resp.text[:500].lower()
        if "<html" in text_head or "sign in" in text_head or "accounts.google" in text_head:
            raise PermissionError(
                "Google Sheets returned an HTML page instead of CSV. "
                "This usually means the spreadsheet is not shared publicly or requires login. "
                "Fix by sharing as 'Anyone with the link can view', or use --google-creds-json, "
                "or download the tab as CSV and read it locally."
            )

    # pandas can read from a string buffer
    from io import StringIO

    return pd.read_csv(StringIO(resp.text))


def read_google_sheet_service_account(
    ref: GoogleSheetRef, *, google_creds_json: str, timeout_s: int = 30
) -> pd.DataFrame:
    """Read a Google Sheet tab using a service account.

    Requires:
      pip install gspread google-auth

    And a service account JSON file content passed in `google_creds_json`.
    """
    try:
        import gspread  # type: ignore
        from google.oauth2.service_account import Credentials  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Reading via service account requires packages: gspread google-auth. "
            "Install with: pip install gspread google-auth"
        ) from e

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds_info = json.loads(google_creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)

    sh = client.open_by_key(ref.spreadsheet_id)
    ws = sh.worksheet(ref.sheet_name)

    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()

    header = values[0]
    rows = values[1:]
    return pd.DataFrame(rows, columns=header)


def read_google_sheet(
    spreadsheet_id: str,
    sheet_name: str,
    *,
    google_creds_json: Optional[str] = None,
) -> pd.DataFrame:
    """Read a Google Sheet tab.

    Tries public CSV first (fast, no auth). If creds are provided, uses service
    account instead.
    """
    ref = GoogleSheetRef(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)

    if google_creds_json:
        return read_google_sheet_service_account(ref, google_creds_json=google_creds_json)

    return read_google_sheet_public_csv(ref)


def read_local_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(Path(path))


def read_local_json(path: str | Path) -> Any:
    with open(Path(path), "r", encoding="utf-8") as f:
        return json.load(f)


def read_gcs_json_folder(
    bucket_name: str,
    prefix: str,
    *,
    project: Optional[str] = None,
) -> list[Any]:
    """
    Read all JSON files from a Google Cloud Storage folder (prefix).

    Requirements:
      pip install google-cloud-storage

    Authentication:
      Uses Application Default Credentials (ADC).
      Make sure you ran:
        gcloud auth application-default login
      or set GOOGLE_APPLICATION_CREDENTIALS to a service account key file.
    """
    try:
        from google.cloud import storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Reading from GCS requires google-cloud-storage. "
            "Install with: pip install google-cloud-storage"
        ) from e

    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)

    blobs = bucket.list_blobs(prefix=prefix)

    records: list[Any] = []
    for blob in blobs:
        if not blob.name.lower().endswith(".json"):
            continue

        raw = blob.download_as_text(encoding="utf-8")
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in gs://{bucket_name}/{blob.name}") from e

    return records


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read project data inputs")

    p.add_argument(
        "--spreadsheet-id",
        default="1SWsFfxcZbU24bn0pqcP6JyNrBvRmSHBVj02HLNv--Uk",
        help="Google Spreadsheet ID (default: project sheet)",
    )
    p.add_argument(
        "--sheet",
        default="honduras",
        help="Sheet/tab name to read (default: Honduras)",
    )
    p.add_argument(
        "--google-creds-json",
        default=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        help=(
            "Service account JSON content (string). If not provided, the script "
            "tries public CSV export. You can also set env var GOOGLE_SERVICE_ACCOUNT_JSON."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        help="Optional path to write the loaded sheet as CSV.",
    )
    p.add_argument(
        "--print-head",
        action="store_true",
        help="Print df.head() to stdout.",
    )
    p.add_argument(
        "--gcs-bucket",
        default=None,
        help="Google Cloud Storage bucket name (e.g. my-bucket)",
    )
    p.add_argument(
        "--gcs-prefix",
        default=None,
        help="Folder/prefix inside the bucket (e.g. data/honduras/)",
    )
    p.add_argument(
        "--gcs-project",
        default=None,
        help="Optional GCP project ID for the storage client.",
    )

    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # GCS JSON folder mode
    if args.gcs_bucket and args.gcs_prefix:
        records = read_gcs_json_folder(
            bucket_name=args.gcs_bucket,
            prefix=args.gcs_prefix,
            project=args.gcs_project,
        )

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

        if args.print_head:
            print(records[:3])

        return

    df = read_google_sheet(
        spreadsheet_id=args.spreadsheet_id,
        sheet_name=args.sheet,
        google_creds_json=args.google_creds_json,
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)

    if args.print_head:
        # Keep it readable even for wide sheets
        with pd.option_context("display.max_columns", 200, "display.width", 120):
            print(df.head(20))


if __name__ == "__main__":
    main()
