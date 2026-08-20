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

psycopg is imported at module level, guarded by try/except, so tests
can monkeypatch this module's `psycopg` name directly instead of
needing the real driver or a live database.
"""

from __future__ import annotations

import logging
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
