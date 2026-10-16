"""Postgres data layer for scrapping-tools (replaces Firestore).

Each function opens its own short-lived connection (autocommit) — no global
pool, which is the right shape for serverless functions on Neon.

Rows are returned as plain dicts. Known columns are mapped to real columns;
any other field is stored in the ``extra`` JSONB column. On read, the result
is ``{**extra, **columns, "_doc_id": id}`` (columns take precedence and
``_doc_id`` is never persisted).
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from trust_api.scrapping_tools.core.config import settings

POSTS_COLUMNS = {
    "post_id",
    "platform",
    "country",
    "candidate_id",
    "status",
    "replies_count",
    "max_posts_replies",
    "created_at",
    "updated_at",
}

JOBS_COLUMNS = {
    "job_id",
    "post_doc_id",
    "post_id",
    "platform",
    "country",
    "candidate_id",
    "status",
    "max_posts_replies",
    "sort_by",
    "retry_count",
    "execution_log_file",
    "error_log_file",
    "created_at",
    "updated_at",
}

_VALID_ORDER_BY = {"created_at", "updated_at"}


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Open a short-lived autocommit connection from DATABASE_URL."""
    conn = psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def _split_fields(fields: dict[str, Any], columns: set[str]) -> tuple[dict, dict]:
    """Split a fields dict into (column values, extra values)."""
    cols = {k: v for k, v in fields.items() if k in columns}
    extra = {k: v for k, v in fields.items() if k not in columns and k not in ("id", "_doc_id")}
    return cols, extra


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    row = dict(row)
    doc_id = row.pop("id")
    extra = row.pop("extra", None) or {}
    if isinstance(extra, str):
        extra = json.loads(extra)
    result = {**extra, **row}
    result["_doc_id"] = doc_id
    return result


def _build_filters(
    status: str,
    candidate_id: str | None,
    platform: str | None,
    country: str | None,
    extra_filters: list[tuple[str, Any]] | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["status = %s"]
    params: list[Any] = [status]
    if candidate_id:
        clauses.append("candidate_id = %s")
        params.append(candidate_id)
    if platform:
        clauses.append("lower(platform) = %s")
        params.append(platform.lower())
    if country:
        clauses.append("lower(country) = %s")
        params.append(country.lower())
    if extra_filters:
        for clause, value in extra_filters:
            clauses.append(clause)
            params.append(value)
    return " AND ".join(clauses), params


def _list(
    table: str,
    status: str,
    *,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    order_by: str = "created_at",
    limit: int | None = None,
    extra_filters: list[tuple[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if order_by not in _VALID_ORDER_BY:
        raise ValueError(
            f"Invalid order_by: {order_by!r}. Must be one of {sorted(_VALID_ORDER_BY)}"
        )
    where, params = _build_filters(status, candidate_id, platform, country, extra_filters)
    sql = f"SELECT * FROM {table} WHERE {where} ORDER BY {order_by} ASC"  # noqa: S608
    if limit is not None and limit > 0:
        sql += " LIMIT %s"
        params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def _get(table: str, doc_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (doc_id,)).fetchone()  # noqa: S608
    return _row_to_dict(row)


def _insert(table: str, fields: dict[str, Any], columns: set[str]) -> str:
    cols, extra = _split_fields(fields, columns)
    doc_id = fields.get("id") or fields.get("_doc_id")
    col_names = list(cols.keys())

    all_cols = (["id"] if doc_id else []) + col_names + ["extra"]
    placeholders = ["%s"] * len(all_cols)
    placeholders[-1] = "%s::jsonb"
    params = (
        ([doc_id] if doc_id else [])
        + [cols[c] for c in col_names]
        + [json.dumps(extra, default=str)]
    )

    sql = f"INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({', '.join(placeholders)})"  # noqa: S608
    if doc_id:
        # Upsert preserving the provided id (used by the Firestore->Neon migration)
        updates = [f"{c} = EXCLUDED.{c}" for c in col_names] + ["extra = EXCLUDED.extra"]
        sql += f" ON CONFLICT (id) DO UPDATE SET {', '.join(updates)}"
    sql += " RETURNING id"

    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return row["id"]


def _update(table: str, doc_id: str, fields: dict[str, Any], columns: set[str]) -> None:
    fields = dict(fields)
    if "updated_at" not in fields:
        fields["updated_at"] = datetime.now(timezone.utc)
    cols, extra = _split_fields(fields, columns)
    set_clauses = [f"{k} = %s" for k in cols]
    params: list[Any] = list(cols.values())
    if extra:
        set_clauses.append("extra = extra || %s::jsonb")
        params.append(json.dumps(extra, default=str))
    sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = %s"  # noqa: S608
    params.append(doc_id)
    with get_conn() as conn:
        conn.execute(sql, params)


def _count(
    table: str,
    status: str,
    *,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
) -> int:
    where, params = _build_filters(status, candidate_id, platform, country)
    with get_conn() as conn:
        row = conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}", params).fetchone()  # noqa: S608
    return row["n"]


# ---------------------------------------------------------------------------
# posts
# ---------------------------------------------------------------------------


def list_posts(
    status: str,
    *,
    platform: str | None = None,
    candidate_id: str | None = None,
    country: str | None = None,
    order_by: str = "created_at",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return _list(
        settings.posts_table,
        status,
        platform=platform,
        candidate_id=candidate_id,
        country=country,
        order_by=order_by,
        limit=limit,
    )


def list_posts_where(
    status: str,
    *,
    not_platform: str | None = None,
    order_by: str = "created_at",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List posts excluding a platform (used for 'non-twitter' queries)."""
    extra = [("lower(platform) != %s", not_platform.lower())] if not_platform else None
    return _list(settings.posts_table, status, order_by=order_by, limit=limit, extra_filters=extra)


def get_post(doc_id: str) -> dict[str, Any] | None:
    return _get(settings.posts_table, doc_id)


def update_post(doc_id: str, fields: dict[str, Any]) -> None:
    _update(settings.posts_table, doc_id, fields, POSTS_COLUMNS)


def insert_post(fields: dict[str, Any]) -> str:
    return _insert(settings.posts_table, fields, POSTS_COLUMNS)


def count_posts(
    status: str,
    *,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
) -> int:
    return _count(
        settings.posts_table,
        status,
        candidate_id=candidate_id,
        platform=platform,
        country=country,
    )


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def insert_job(fields: dict[str, Any]) -> str:
    return _insert(settings.jobs_table, fields, JOBS_COLUMNS)


def list_jobs(
    status: str,
    *,
    post_id: str | None = None,
    platform: str | None = None,
    candidate_id: str | None = None,
    country: str | None = None,
    order_by: str = "created_at",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    extra = [("post_id = %s", post_id)] if post_id else None
    return _list(
        settings.jobs_table,
        status,
        candidate_id=candidate_id,
        platform=platform,
        country=country,
        order_by=order_by,
        limit=limit,
        extra_filters=extra,
    )


def get_job(doc_id: str) -> dict[str, Any] | None:
    return _get(settings.jobs_table, doc_id)


def update_job(doc_id: str, fields: dict[str, Any]) -> None:
    _update(settings.jobs_table, doc_id, fields, JOBS_COLUMNS)


def count_jobs(
    status: str,
    *,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
) -> int:
    return _count(
        settings.jobs_table,
        status,
        candidate_id=candidate_id,
        platform=platform,
        country=country,
    )


def job_exists(post_id: str, status: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {settings.jobs_table} WHERE post_id = %s AND status = %s LIMIT 1",  # noqa: S608
            (post_id, status),
        ).fetchone()
    return row is not None
