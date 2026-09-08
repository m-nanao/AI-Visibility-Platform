"""Minimal analysis-history persistence: brands / analysis_runs /
analysis_results (see docs/19_minimum_db_migration_design.md,
backend/migrations/001_initial_analysis_history.sql).

DB persistence is entirely optional and non-blocking for /analyze:

- Skipped outright when DB_SAVE_ENABLED is not "true" or DATABASE_URL
  is unset (see services/db_settings.py) — no connection is ever
  attempted, so an unconfigured environment behaves exactly like
  before this module existed.
- Any failure (connection, query, missing driver) is caught inside
  save_analysis_history() itself and logged; it never raises, so a DB
  outage or misconfiguration can never break /analyze (see main.py,
  which additionally wraps the call in its own try/except as a second
  layer of defense).

Individual observation tables (input_urls/documents/cooccurrence_terms/
context_analyses/ai_overview_observations/chatgpt_observations/
common_crawl_fetches/analysis_sources/analysis_result_sources) are
intentionally out of scope — see
docs/19_minimum_db_migration_design.md "4. 初期実装で作らないテーブル".
The whole /analyze response is stored as one result_json blob per
AnalysisRun instead.

This module also has the read side of the same 3 tables —
list_analysis_runs()/get_analysis_run(), backing GET /analysis-runs and
GET /analysis-runs/{id} (see main.py and
docs/20_analysis_history_read_api_design.md). Unlike
save_analysis_history() above, these two **do not swallow failures**:
a connection/query error raises AnalysisHistoryReadError so main.py can
turn it into a 503, since a caller of a read API needs to know their
request failed (see docs/20_analysis_history_read_api_design.md "11.
backend repository設計案"). Callers must check
services.db_settings.is_history_read_enabled() themselves before
calling either function — neither checks READ_HISTORY_ENABLED itself,
only that DATABASE_URL is present (mirrors save_analysis_history() only
checking configuration it owns).

psycopg is imported at module level, guarded by try/except, so tests
can monkeypatch this module's `psycopg` name directly instead of
needing the real driver or a live database.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from services.db_settings import load_db_settings

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised when the optional driver isn't installed
    psycopg = None
    Jsonb = None

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


class AnalysisHistoryReadError(Exception):
    """Raised by list_analysis_runs()/get_analysis_run() when reading
    saved analysis history fails — connection failure, query failure,
    or the psycopg driver not being installed. Callers (main.py) catch
    this and respond 503, distinct from get_analysis_run() returning
    None for "no such id" (a 404, not a failure)."""


@dataclass(frozen=True)
class AnalysisHistorySaveResult:
    """Returned by save_analysis_history() only on a full success —
    see its docstring for the skip/failure cases (both return None)."""

    analysis_run_id: str
    brand_id: str


def _maybe_jsonb(value: dict[str, Any] | None):
    """Wraps a dict for a jsonb column, or passes None through as a
    real SQL NULL (rather than a JSON "null") for optional columns."""
    return None if value is None else Jsonb(value)


def save_analysis_history(
    *,
    brand_name: str,
    canonical_domain: str | None,
    input_snapshot: dict[str, Any],
    source_summary: dict[str, Any] | None,
    result_json: dict[str, Any],
    visibility_score: int | None,
    meta_json: dict[str, Any] | None,
    status: str,
) -> AnalysisHistorySaveResult | None:
    """Best-effort save of one analysis run to Postgres.

    Returns None when:
    - DB persistence is not configured (DB_SAVE_ENABLED/DATABASE_URL —
      see services/db_settings.py); no connection is attempted.
    - The psycopg driver is not installed.
    - Anything about the connection/query fails (logged here via
      logger.exception before returning).

    Returns the created brand/analysis_run ids only on full success.
    Never raises.
    """

    settings = load_db_settings()
    if not (settings.save_enabled and settings.database_url):
        return None

    if psycopg is None:
        logger.warning(
            "DB_SAVE_ENABLED is true but the psycopg driver is not installed; skipping DB save"
        )
        return None

    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # Brand: reuse an existing row by exact name match if
                # one exists (simple get), otherwise create one — see
                # docs/19_minimum_db_migration_design.md "5. brands
                # テーブル案", which explicitly says not to enforce
                # strict dedup here.
                cur.execute(
                    "select id from brands where name = %s order by created_at desc limit 1",
                    (brand_name,),
                )
                row = cur.fetchone()
                if row is not None:
                    brand_id = row[0]
                else:
                    cur.execute(
                        """
                        insert into brands (name, canonical_domain)
                        values (%s, %s)
                        returning id
                        """,
                        (brand_name, canonical_domain),
                    )
                    brand_id = cur.fetchone()[0]

                cur.execute(
                    """
                    insert into analysis_runs
                        (brand_id, status, input_snapshot, source_summary, completed_at)
                    values (%s, %s, %s, %s, now())
                    returning id
                    """,
                    (
                        brand_id,
                        status,
                        Jsonb(input_snapshot),
                        _maybe_jsonb(source_summary),
                    ),
                )
                analysis_run_id = cur.fetchone()[0]

                cur.execute(
                    """
                    insert into analysis_results
                        (analysis_run_id, visibility_score, result_json, meta_json)
                    values (%s, %s, %s, %s)
                    """,
                    (
                        analysis_run_id,
                        visibility_score,
                        Jsonb(result_json),
                        _maybe_jsonb(meta_json),
                    ),
                )
            conn.commit()

        return AnalysisHistorySaveResult(
            analysis_run_id=str(analysis_run_id),
            brand_id=str(brand_id),
        )
    except Exception:
        logger.exception("Failed to save analysis history to DB")
        return None


def _require_connectable() -> str:
    """Raises AnalysisHistoryReadError if a DB connection can't even be
    attempted (missing driver/DATABASE_URL); otherwise returns the
    connection string. Shared by list_analysis_runs()/get_analysis_run().
    """
    if psycopg is None:
        raise AnalysisHistoryReadError("psycopg driver is not installed")

    database_url = load_db_settings().database_url
    if not database_url:
        raise AnalysisHistoryReadError("DATABASE_URL is not configured")

    return database_url


def list_analysis_runs(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    brand: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Returns saved analysis run summaries (brands ⋈ analysis_runs ⋈
    analysis_results), newest first — see
    docs/20_analysis_history_read_api_design.md "5. GET /analysis-runs
    の設計案". Deliberately never includes result_json (see that
    section's "返さないもの").

    `limit` is clamped to [1, MAX_LIST_LIMIT] and `offset` to >= 0
    regardless of what's passed in — defense in depth alongside
    main.py's own FastAPI query validation.

    Raises AnalysisHistoryReadError on any connection/query failure.
    Does not itself check READ_HISTORY_ENABLED — callers must call
    services.db_settings.is_history_read_enabled() first.
    """
    database_url = _require_connectable()

    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    conditions: list[str] = []
    params: list[Any] = []
    if brand is not None:
        conditions.append("b.name = %s")
        params.append(brand)
    if status is not None:
        conditions.append("ar.status = %s")
        params.append(status)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""

    query = f"""
        select
            ar.id,
            b.name,
            b.canonical_domain,
            ar.status,
            res.visibility_score,
            ar.source_summary,
            ar.started_at,
            ar.completed_at,
            ar.created_at
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        left join analysis_results res on res.analysis_run_id = ar.id
        {where_clause}
        order by ar.created_at desc
        limit %s offset %s
    """
    params.extend([limit, offset])

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("Failed to list analysis runs from DB")
        raise AnalysisHistoryReadError("failed to query analysis history") from exc

    return [
        {
            "id": str(row[0]),
            "brandName": row[1],
            "canonicalDomain": row[2],
            "status": row[3],
            "visibilityScore": row[4],
            "sourceSummary": row[5],
            "startedAt": row[6].isoformat() if row[6] is not None else None,
            "completedAt": row[7].isoformat() if row[7] is not None else None,
            "createdAt": row[8].isoformat() if row[8] is not None else None,
        }
        for row in rows
    ]


def get_analysis_run(analysis_run_id: str) -> dict[str, Any] | None:
    """Returns one saved analysis run's full detail (brand info, run
    info, and — unlike list_analysis_runs() — the full result_json/
    meta_json), or None when no analysis_runs row has this id (main.py
    turns that into a 404) — see
    docs/20_analysis_history_read_api_design.md "6. GET
    /analysis-runs/{id} の設計案".

    A malformed (non-UUID) `analysis_run_id` is treated the same as
    "not found" (returns None without attempting a query) rather than
    raising or reaching the DB with an invalid value.

    Raises AnalysisHistoryReadError on any other connection/query
    failure. Does not itself check READ_HISTORY_ENABLED — callers must
    call services.db_settings.is_history_read_enabled() first.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    query = """
        select
            ar.id,
            b.id,
            b.name,
            b.canonical_domain,
            ar.status,
            ar.input_snapshot,
            ar.source_summary,
            ar.started_at,
            ar.completed_at,
            res.result_json,
            res.meta_json
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        left join analysis_results res on res.analysis_run_id = ar.id
        where ar.id = %s
        order by res.created_at desc
        limit 1
    """

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (analysis_run_id,))
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to get analysis run from DB")
        raise AnalysisHistoryReadError("failed to query analysis history") from exc

    if row is None:
        return None

    return {
        "id": str(row[0]),
        "brand": {
            "id": str(row[1]),
            "name": row[2],
            "canonicalDomain": row[3],
        },
        "run": {
            "status": row[4],
            "inputSnapshot": row[5],
            "sourceSummary": row[6],
            "startedAt": row[7].isoformat() if row[7] is not None else None,
            "completedAt": row[8].isoformat() if row[8] is not None else None,
        },
        "result": row[9],
        "meta": row[10],
    }
