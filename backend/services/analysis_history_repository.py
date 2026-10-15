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

get_previous_analysis_run_for_brand() extends this read side to back
GET /analysis-runs/{id}/comparison (see main.py and
docs/25_analysis_history_comparison_design.md) — same
non-swallowing/READ_HISTORY_ENABLED-is-the-caller's-job contract as
the two functions above. The actual diff computation lives in
services/analysis_history_comparison.py as pure functions, kept
separate from this module's DB access.

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
from services.history_mode_summary import build_mode_summary

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised when the optional driver isn't installed
    psycopg = None
    Jsonb = None

# Used by create_queued_analysis_run()'s defense-in-depth path (see its
# docstring) — guarded the same way as psycopg/Jsonb above so this
# module still imports cleanly when the optional driver isn't
# installed.
UniqueViolation = psycopg.errors.UniqueViolation if psycopg is not None else None

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


def get_default_project_id(cur) -> str | None:
    """Looks up the default project's id (organizations.slug = 'default',
    projects.slug = 'default') using an already-open cursor — see
    docs/28_supabase_auth_rls_migration_design.md "7. default
    organization / default project の扱い" and
    backend/migrations/002_add_organizations_projects.sql.

    Returns None when no such row exists (e.g. migration 002 hasn't
    been applied to this database yet) rather than raising, so callers
    can decide how to degrade — save_analysis_history() below skips
    the save entirely in that case."""
    cur.execute(
        """
        select p.id
        from projects p
        join organizations o on o.id = p.organization_id
        where p.slug = 'default' and o.slug = 'default'
        limit 1
        """
    )
    row = cur.fetchone()
    return str(row[0]) if row is not None else None


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
                # default project (organizations/projects with
                # slug='default', see backend/migrations/002_add_organizations_projects.sql)
                # is required for the project_id columns below. If it
                # doesn't exist yet (e.g. migration 002 hasn't been
                # applied to this database), skip the save entirely
                # rather than writing new brands/analysis_runs rows
                # with no project_id — see
                # docs/28_supabase_auth_rls_migration_design.md "21.
                # 本番適用状況" for why this is preferred over saving
                # without a project_id.
                default_project_id = get_default_project_id(cur)
                if default_project_id is None:
                    logger.warning(
                        "default project (organizations.slug='default', "
                        "projects.slug='default') not found; skipping analysis history save"
                    )
                    return None

                # Brand: reuse an existing row by exact name match if
                # one exists (simple get), otherwise create one — see
                # docs/19_minimum_db_migration_design.md "5. brands
                # テーブル案", which explicitly says not to enforce
                # strict dedup here. An existing brand that already has
                # a project_id is left untouched; one with project_id
                # still null (e.g. from before this backfill existed)
                # is assigned the default project.
                cur.execute(
                    "select id, project_id from brands where name = %s order by created_at desc limit 1",
                    (brand_name,),
                )
                row = cur.fetchone()
                if row is not None:
                    brand_id, brand_project_id = row
                    if brand_project_id is None:
                        cur.execute(
                            "update brands set project_id = %s where id = %s",
                            (default_project_id, brand_id),
                        )
                else:
                    cur.execute(
                        """
                        insert into brands (name, canonical_domain, project_id)
                        values (%s, %s, %s)
                        returning id
                        """,
                        (brand_name, canonical_domain, default_project_id),
                    )
                    brand_id = cur.fetchone()[0]

                cur.execute(
                    """
                    insert into analysis_runs
                        (brand_id, project_id, status, input_snapshot, source_summary, completed_at)
                    values (%s, %s, %s, %s, %s, now())
                    returning id
                    """,
                    (
                        brand_id,
                        default_project_id,
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


def get_connection():
    """Opens a short-lived DB connection for callers outside this
    module (main.py) that need to pass an already-open connection to
    services.project_access.py's access-control helpers — those take a
    connection rather than a database_url, one level up from
    get_default_project_id()'s cursor-taking style above.

    Raises AnalysisHistoryReadError if the psycopg driver isn't
    installed or DATABASE_URL isn't configured (via
    _require_connectable()). A genuine connection failure (DB
    unreachable, auth failure, etc.) raises whatever psycopg itself
    raises when the returned object is entered via `with` — callers
    should wrap their `with get_connection() as conn:` block in a
    broad `except Exception` and treat any failure the same way (503),
    mirroring how list_analysis_runs()/get_analysis_run() already
    handle connection failures.
    """
    database_url = _require_connectable()
    return psycopg.connect(database_url, connect_timeout=5)


def _extract_source_urls(input_snapshot: Any) -> list[str]:
    """Pulls the input URL strings back out of a saved
    analysis_runs.input_snapshot blob — added for
    fix/history-domain-search so the history list can offer domain
    search even though brands.canonical_domain is never actually
    populated today (main.py's save_analysis_history() call always
    passes `canonical_domain=None`).

    `input_snapshot` is the exact dict main.py built from the original
    `/analyze` request body (see its `{"brandName": ..., "urls": ...,
    ...}` literal) — `urls` there is `AnalyzeRequest.urls` verbatim,
    the raw strings the caller typed in, not yet parsed into hostnames
    (hostname extraction is a frontend concern, see
    app/lib/analysis-history.ts's buildDomainSearchVariants()).

    Deliberately defensive about shape: `input_snapshot` is untyped
    JSON from the database, and this function is reached for every
    saved run regardless of how old it is or what shape its
    input_snapshot happens to have. Returns `[]` (never raises) for
    anything other than a dict with a `urls` key holding a list of
    strings — covers input_snapshot being None, `urls` being absent
    (schema predates it — never actually happened, but defensive
    anyway), or a non-list/non-string entry.
    """
    if not isinstance(input_snapshot, dict):
        return []
    urls = input_snapshot.get("urls")
    if not isinstance(urls, list):
        return []
    return [url for url in urls if isinstance(url, str) and url.strip()]


def list_analysis_runs(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    brand: str | None = None,
    status: str | None = None,
    project_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Returns saved analysis run summaries (brands ⋈ analysis_runs ⋈
    analysis_results), newest first — see
    docs/20_analysis_history_read_api_design.md "5. GET /analysis-runs
    の設計案". Deliberately never includes result_json (see that
    section's "返さないもの"). Each item's `sourceUrls` is derived from
    `analysis_runs.input_snapshot` (see _extract_source_urls() above)
    — added so the frontend history list can search by domain even
    though `canonicalDomain` (from `brands.canonical_domain`) is never
    actually populated by save_analysis_history() today. Always
    excludes a soft-deleted run
    (analysis_runs.deleted_at is not null — see
    backend/migrations/003_add_deleted_at_to_analysis_runs.sql and
    soft_delete_analysis_run() below) regardless of mode/project_ids;
    there is no "show deleted runs too" option on this endpoint.

    `limit` is clamped to [1, MAX_LIST_LIMIT] and `offset` to >= 0
    regardless of what's passed in — defense in depth alongside
    main.py's own FastAPI query validation.

    `project_ids` is optional groundwork for
    services.project_access.get_accessible_project_ids() (see
    docs/32_backend_jwt_verification_design.md "9. project権限判定") —
    no caller passes it yet, and the existing HISTORY_READ_TOKEN-gated
    callers in main.py are unaffected. `None` (the default) means "no
    project filter, return everything" (today's behavior, unchanged).
    An explicit `[]` means "no accessible projects" and short-circuits
    to `[]` without touching the DB at all, since an `IN ()` clause
    with no values is either a SQL error or always-false depending on
    the driver — better to never construct one. A non-empty list adds
    an `ar.project_id in (...)` condition with each id passed as its
    own parameterized placeholder (never interpolated into the query
    string).

    Raises AnalysisHistoryReadError on any connection/query failure.
    Does not itself check READ_HISTORY_ENABLED — callers must call
    services.db_settings.is_history_read_enabled() first.
    """
    if project_ids is not None and len(project_ids) == 0:
        return []

    database_url = _require_connectable()

    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    # "ar.deleted_at is null" is unconditional (not behind an opt-out) —
    # this endpoint never has a "show deleted runs too" mode.
    conditions: list[str] = ["ar.deleted_at is null"]
    params: list[Any] = []
    if brand is not None:
        conditions.append("b.name = %s")
        params.append(brand)
    if status is not None:
        conditions.append("ar.status = %s")
        params.append(status)
    if project_ids is not None:
        placeholders = ", ".join(["%s"] * len(project_ids))
        conditions.append(f"ar.project_id in ({placeholders})")
        params.extend(project_ids)
    where_clause = f"where {' and '.join(conditions)}"

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
            ar.created_at,
            res.meta_json,
            ar.input_snapshot,
            ar.is_important
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
            # Derived from meta_json only (see
            # services/history_mode_summary.py) — meta_json itself is
            # never included in the returned dict, keeping this
            # endpoint's "never includes result_json/meta_json" payload
            # discipline intact for everything except this small summary.
            "modeSummary": build_mode_summary(row[9]),
            # Derived from input_snapshot only (see
            # _extract_source_urls() above) — input_snapshot itself is
            # never included in the returned dict, same discipline as
            # modeSummary above. Added for fix/history-domain-search
            # since canonicalDomain is never actually populated today.
            "sourceUrls": _extract_source_urls(row[10]),
            # analysis_runs.is_important (backend/migrations/
            # 004_add_is_important_to_analysis_runs.sql) — see
            # docs/38_history_marking_design.md 案A.
            "isImportant": bool(row[11]),
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
    raising or reaching the DB with an invalid value. A soft-deleted
    run (analysis_runs.deleted_at is not null) is also treated as "not
    found" here — see backend/migrations/003_add_deleted_at_to_analysis_runs.sql
    and soft_delete_analysis_run() below — so main.py's existing "404
    when None" handling already does the right thing without needing
    its own deleted-run check.

    The returned dict also includes a top-level `"projectId"` (the
    run's `analysis_runs.project_id`, or `None` for a legacy row saved
    before that column was populated) — used by main.py's
    JWT-authenticated comparison path to keep the previous run lookup
    within the same project (see
    docs/32_backend_jwt_verification_design.md "project境界"). It is
    never included in any API response model (main.py picks fields out
    of this dict by name rather than unpacking it wholesale).

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
            res.meta_json,
            ar.project_id,
            ar.is_important
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        left join analysis_results res on res.analysis_run_id = ar.id
        where ar.id = %s and ar.deleted_at is null
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
        "projectId": str(row[11]) if row[11] is not None else None,
        # analysis_runs.is_important (backend/migrations/
        # 004_add_is_important_to_analysis_runs.sql) — see
        # docs/38_history_marking_design.md 案A.
        "isImportant": bool(row[12]),
    }


def get_previous_analysis_run_for_brand(
    analysis_run_id: str, *, project_id: str | None = None
) -> dict[str, Any] | None:
    """Returns the same brand's most recent analysis run started
    before `analysis_run_id`'s own run, or None when there isn't one
    yet (or when `analysis_run_id` itself doesn't exist) — backs
    GET /analysis-runs/{id}/comparison (see
    docs/25_analysis_history_comparison_design.md "5. 比較対象の選び
    方"). `brand_id` is the only comparison key used in this initial
    version; `canonical_domain` matching is deliberately not attempted.

    A single self-join query finds the previous row directly from
    `analysis_run_id`, so callers don't need to fetch the current run
    first just to learn its brand_id/created_at. A soft-deleted
    candidate (`prev.deleted_at is not null`) is skipped, so a deleted
    run never surfaces as someone else's "previous" comparison target —
    `analysis_run_id` itself being deleted is a separate case, already
    handled upstream by get_analysis_run() returning None before this
    function is ever called (see main.py).

    `project_id`, when given, additionally restricts the previous run
    to `prev.project_id = project_id` — used by main.py's
    JWT-authenticated comparison path so a comparison can never surface
    a previous run from a different project than the one the caller
    was already authorized to see for the current run (see
    docs/32_backend_jwt_verification_design.md "project境界"; a brand
    is expected to belong to one project, but this filter is a second,
    explicit line of defense rather than relying on that assumption
    alone). `None` (the default) keeps the existing brand-only
    matching, unchanged for the HISTORY_READ_TOKEN path.

    A malformed (non-UUID) `analysis_run_id` is treated the same as
    "no previous run" (returns None without attempting a query) —
    mirrors get_analysis_run()'s handling. Callers separately confirm
    `analysis_run_id` itself exists (e.g. via get_analysis_run()) to
    distinguish a 404 from a genuinely first-ever run.

    Raises AnalysisHistoryReadError on any connection/query failure.
    Does not itself check READ_HISTORY_ENABLED — callers must call
    services.db_settings.is_history_read_enabled() first.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    params: list[Any] = [analysis_run_id]
    project_filter = ""
    if project_id is not None:
        project_filter = "and prev.project_id = %s"
        params.append(project_id)

    query = f"""
        select
            prev.id,
            prev.started_at,
            res.result_json
        from analysis_runs prev
        join analysis_runs current_run on current_run.id = %s
        left join analysis_results res on res.analysis_run_id = prev.id
        where prev.brand_id = current_run.brand_id
          and prev.created_at < current_run.created_at
          and prev.deleted_at is null
          {project_filter}
        order by prev.created_at desc
        limit 1
    """

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to get previous analysis run from DB")
        raise AnalysisHistoryReadError("failed to query analysis history") from exc

    if row is None:
        return None

    return {
        "id": str(row[0]),
        "startedAt": row[1].isoformat() if row[1] is not None else None,
        "result": row[2],
    }


def soft_delete_analysis_run(analysis_run_id: str) -> bool:
    """Soft-deletes one analysis_runs row by setting `deleted_at =
    now()` — never `DELETE FROM analysis_runs` (see
    backend/migrations/003_add_deleted_at_to_analysis_runs.sql).
    `analysis_results`/`brands` are never touched.

    Deliberately unscoped by project — main.py's DELETE
    /analysis-runs/{id} is responsible for authorizing the caller
    *before* calling this, exactly like the existing GET detail/
    comparison endpoints authorize via
    services.project_access.can_user_access_analysis_run() first and
    only then fetch by bare id. This keeps the authorization check and
    the id-shaped operation it gates as two separate, individually
    reviewable steps, rather than re-deriving scoping rules inside two
    different repository functions.

    Returns True when the row was just soft-deleted by this call, OR
    was already soft-deleted (a repeat DELETE is treated as a
    successful no-op, not an error — see the task's "すでに削除済みなら
    成功扱いでもよい"). Returns False when `analysis_run_id` doesn't
    exist or is malformed.

    Raises AnalysisHistoryReadError on any connection/query failure —
    reuses this module's existing read-error type rather than adding a
    new one, since every caller already has an
    `except AnalysisHistoryReadError: return 503` in place.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set deleted_at = now()
                    where id = %s and deleted_at is null
                    returning id
                    """,
                    (analysis_run_id,),
                )
                deleted_now = cur.fetchone() is not None

                already_deleted = False
                if not deleted_now:
                    # Not updated just now — tell "already deleted" apart
                    # from "doesn't exist" with one more lookup, so a
                    # repeat DELETE of the same run is still reported as
                    # success.
                    cur.execute(
                        "select 1 from analysis_runs where id = %s and deleted_at is not null",
                        (analysis_run_id,),
                    )
                    already_deleted = cur.fetchone() is not None
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to soft-delete analysis run")
        raise AnalysisHistoryReadError("failed to delete analysis history") from exc

    return deleted_now or already_deleted


def set_analysis_run_important(analysis_run_id: str, *, is_important: bool) -> bool:
    """Sets one analysis_runs row's `is_important` flag — see
    backend/migrations/004_add_is_important_to_analysis_runs.sql and
    docs/38_history_marking_design.md 案A/"7. API設計案". Backs PATCH
    /analysis-runs/{id}/important.

    Returns True when a row was updated, False when `analysis_run_id`
    doesn't exist, is malformed, or is soft-deleted (`deleted_at is not
    null`) — main.py turns False into a 404, mirroring
    soft_delete_analysis_run()/update_analysis_result()'s return-bool
    convention above. A soft-deleted run is treated as "not found" here
    (not updatable), the same as get_analysis_run() already treats it,
    so a deleted history entry can't be resurrected into the important
    list through this endpoint.

    Deliberately unscoped by project, exactly like
    soft_delete_analysis_run()/update_analysis_result() above — main.py's
    PATCH endpoint is responsible for authorizing the caller against
    `analysis_run_id` *before* calling this.

    Raises AnalysisHistoryReadError on any connection/query failure —
    reuses this module's existing read-error type (every caller already
    has `except AnalysisHistoryReadError: return 503` in place). This
    includes the case where migration 004 hasn't been applied yet (the
    `is_important` column doesn't exist) — the underlying
    "column ... does not exist" error is logged server-side (never
    returned to the caller) and surfaces to the API caller as the same
    503 every other DB failure does.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set is_important = %s
                    where id = %s and deleted_at is null
                    returning id
                    """,
                    (is_important, analysis_run_id),
                )
                updated = cur.fetchone() is not None
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to update analysis run important flag")
        raise AnalysisHistoryReadError("failed to update analysis history") from exc

    return updated


def update_analysis_result(
    analysis_run_id: str, *, result_json: dict[str, Any], meta_json: dict[str, Any] | None
) -> bool:
    """Overwrites one saved analysis run's result_json/meta_json in
    place — added for the Gemini-only re-run feature (see
    services/gemini_rerun.py and POST /analysis-runs/{id}/rerun/gemini)
    so a single AI observation card can be refreshed without re-running
    the rest of `/analyze`. Never touches analysis_runs/brands, and
    never touches analysis_results.visibility_score (Gemini's card has
    no bearing on it) — only result_json/meta_json on the existing row.

    Returns True when a row was updated, False when `analysis_run_id`
    doesn't exist, is malformed, is soft-deleted, or has no
    analysis_results row yet — main.py turns False into a 404, mirroring
    soft_delete_analysis_run()'s return-bool convention above.

    Deliberately unscoped by project, exactly like
    soft_delete_analysis_run() above — main.py's rerun endpoint is
    responsible for authorizing the caller against `analysis_run_id`
    *before* calling this.

    Raises AnalysisHistoryReadError on any connection/query failure —
    reuses this module's existing read-error type (every caller already
    has `except AnalysisHistoryReadError: return 503` in place).
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_results
                    set result_json = %s, meta_json = %s
                    where analysis_run_id = %s
                      and analysis_run_id in (
                          select id from analysis_runs where deleted_at is null
                      )
                    returning id
                    """,
                    (Jsonb(result_json), _maybe_jsonb(meta_json), analysis_run_id),
                )
                updated = cur.fetchone() is not None
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to update analysis result after Gemini rerun")
        raise AnalysisHistoryReadError("failed to update analysis result") from exc

    return updated


# --- Async analysis jobs, Phase 1 only (POST /analysis-jobs, GET
# /analysis-jobs/{id}, GET /analysis-jobs/{id}/result) — see
# docs/40_async_analysis_jobs_design.md. Phase 1 adds exactly one new
# write path (create_queued_analysis_run()) and two new read paths
# (get_analysis_job_status()/get_analysis_job_result()); no worker
# exists yet, so nothing here ever transitions a row away from
# 'queued' — that is Phase 2's job (docs/40 "15").


@dataclass(frozen=True)
class AnalysisJobCreateResult:
    """Returned by create_queued_analysis_run() on success. `created`
    distinguishes "this call inserted a brand-new queued row" (True)
    from "an existing job with the same (project_id,
    created_by_user_id, idempotency_key) was returned instead because
    its stored input matched" (False — see docs/40
    "10.2"). `status` is always "queued" when created=True; when
    created=False it mirrors whatever status the existing job already
    has (any value is possible once Phase 2 ships a worker, though
    Phase 1 itself never writes anything other than "queued")."""

    analysis_run_id: str
    status: str
    created: bool


class AnalysisJobCreateConflictError(Exception):
    """Raised by create_queued_analysis_run() when the same
    (project_id, created_by_user_id, idempotency_key) already has a job
    whose stored input does not match this call's input — see
    docs/40_async_analysis_jobs_design.md "10.2". main.py turns this
    into a 409. Carries the existing job's id for diagnostics, even
    though main.py's 409 body doesn't currently expose it."""

    def __init__(self, existing_analysis_run_id: str):
        super().__init__("idempotency key reused with a different request body")
        self.existing_analysis_run_id = existing_analysis_run_id


class AnalysisJobLimitExceededError(Exception):
    """Raised by create_queued_analysis_run() when creating a new job
    would meet or exceed the project- or user-scoped queued-job limit
    — see docs/40_async_analysis_jobs_design.md "8.3". main.py turns
    this into a 429. `scope` is "project" or "user"."""

    def __init__(self, scope: str, limit: int):
        super().__init__(f"{scope} queued job limit ({limit}) reached")
        self.scope = scope
        self.limit = limit


def _canonicalize_job_input(
    *,
    brand_name: str,
    documents: list[str] | None,
    urls: list[str] | None,
    common_crawl_mode: str | None,
    common_crawl_domain: str | None,
    ai_overview_mode: str | None,
    chatgpt_mode: str | None,
    claude_mode: str | None,
    gemini_mode: str | None,
) -> dict[str, Any]:
    """Normalizes one job-creation request's analysis-input fields
    into the exact shape stored in `analysis_runs.input_snapshot` and
    compared against on an idempotency-key replay (docs/40
    "10.1"/"10.2"). Deliberately does *not* reorder/dedupe `documents`
    or `urls` — a caller sending the same key with a different element
    order is treated as a genuinely different request (see docs/40
    task's "入力差分を意図せず無視しないこと") rather than silently
    normalized away. `brandName` is trimmed (matching main.py's
    existing `/analyze` handling of the same field);
    `commonCrawlDomain` is trimmed and treated as absent when blank,
    matching how an empty string and an omitted field already mean the
    same thing to services/common_crawl_index.py.
    """
    return {
        "brandName": brand_name.strip(),
        "documents": documents,
        "urls": urls,
        "commonCrawlMode": common_crawl_mode,
        "commonCrawlDomain": (common_crawl_domain.strip() or None)
        if common_crawl_domain
        else None,
        "aiOverviewMode": ai_overview_mode,
        "chatgptMode": chatgpt_mode,
        "claudeMode": claude_mode,
        "geminiMode": gemini_mode,
    }


def _fetch_existing_job_by_idempotency_key(
    cur, *, project_id: str, created_by_user_id: str, idempotency_key: str
):
    cur.execute(
        """
        select id, status, input_snapshot
        from analysis_runs
        where project_id = %s
          and created_by_user_id = %s
          and idempotency_key = %s
        limit 1
        """,
        (project_id, created_by_user_id, idempotency_key),
    )
    return cur.fetchone()


def _resolve_job_after_unique_violation(
    database_url: str,
    *,
    project_id: str,
    created_by_user_id: str,
    idempotency_key: str,
    canonical_input: dict[str, Any],
) -> AnalysisJobCreateResult:
    """Defense-in-depth path for create_queued_analysis_run() — see its
    docstring. The transaction that hit the UniqueViolation is already
    aborted, so this re-queries on a brand-new connection."""
    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                existing = _fetch_existing_job_by_idempotency_key(
                    cur,
                    project_id=project_id,
                    created_by_user_id=created_by_user_id,
                    idempotency_key=idempotency_key,
                )
    except Exception as exc:
        logger.exception(
            "Failed to resolve analysis job after unique constraint conflict"
        )
        raise AnalysisHistoryReadError("failed to create analysis job") from exc

    if existing is None:
        # The row that caused the UniqueViolation should exist by
        # definition — if it doesn't, something else is wrong (e.g. it
        # was deleted in between), so this surfaces as a generic
        # failure rather than silently creating a duplicate.
        raise AnalysisHistoryReadError("failed to create analysis job")

    existing_id, existing_status, existing_snapshot = existing
    if existing_snapshot != canonical_input:
        raise AnalysisJobCreateConflictError(str(existing_id))

    return AnalysisJobCreateResult(
        analysis_run_id=str(existing_id), status=existing_status, created=False
    )


def create_queued_analysis_run(
    *,
    project_id: str,
    created_by_user_id: str,
    idempotency_key: str,
    brand_name: str,
    documents: list[str] | None,
    urls: list[str] | None,
    common_crawl_mode: str | None,
    common_crawl_domain: str | None,
    ai_overview_mode: str | None,
    chatgpt_mode: str | None,
    claude_mode: str | None,
    gemini_mode: str | None,
    max_queued_per_project: int,
    max_queued_per_user: int,
) -> AnalysisJobCreateResult:
    """Creates one queued analysis job (Phase 1 of
    docs/40_async_analysis_jobs_design.md "15") — inserts a placeholder
    `analysis_runs` row (status='queued') and a placeholder
    `analysis_results` row (result_json='{}', satisfying its NOT NULL
    constraint — see docs/40 "6.1"), and returns the new
    analysis_run_id immediately. No analysis is ever executed by this
    function, or by anything else Phase 1 adds — there is no worker
    yet (docs/40 "4").

    Idempotency (docs/40 "10"): looks up any existing row with the
    same (project_id, created_by_user_id, idempotency_key) *before*
    inserting anything, inside one transaction guarded by two
    transaction-scoped Postgres advisory locks — one keyed on
    `project_id`, one keyed on `created_by_user_id`, each in its own
    hash namespace via `hashtextextended(id, seed)` (seed 0 for the
    project lock, 1 for the user lock) so a project id and a user id
    can never collide into the same lock key. Both are always acquired
    in the same fixed order (project, then user) by every call to this
    function, which is what rules out a deadlock between two
    transactions each waiting on a lock the other already holds — see
    the inline comment at the lock-acquisition site for the full
    reasoning. This serializes concurrent create attempts for the same
    project *and* concurrent create attempts by the same user (even
    across *different* projects), so two simultaneous requests can
    never both pass the lookup-then-insert check for the same key (a
    plain SELECT-then-INSERT in application code alone would race
    under concurrency — see docs/40 "10.1"/"11.1"). If a matching row
    already exists:
    - same canonicalized input -> returns that job's existing
      id/status with created=False (no new row, no limit check — a
      retry of an already-accepted operation must never be rejected by
      the very limits meant to stop *new* operations).
    - different canonicalized input -> raises
      AnalysisJobCreateConflictError (main.py -> 409).

    Queued-job limits (docs/40 "8.3"): only checked when actually about
    to insert a new row (never on an idempotent replay, see above) —
    counts this *project's* and this *user's* currently-'queued' jobs
    and raises AnalysisJobLimitExceededError if either would meet or
    exceed its limit (main.py -> 429). Both counts are taken inside the
    same doubly-locked transaction, so neither check can be slipped
    past by a burst of concurrent requests — not a burst for the same
    project (the project lock), and not a burst from the same user
    spread across different projects (the user lock, which the
    project-only lock from before this fix could not protect against).

    A psycopg UniqueViolation on the final INSERT (defense in depth —
    the advisory locks above are the primary safeguard; this is the
    last-resort DB-level guarantee, see docs/40 "10") is resolved by
    _resolve_job_after_unique_violation() exactly like the pre-insert
    existing-row branch above.

    Raises AnalysisHistoryReadError on any other connection/query
    failure (mirrors every other function in this module).
    """
    database_url = _require_connectable()

    canonical_input = _canonicalize_job_input(
        brand_name=brand_name,
        documents=documents,
        urls=urls,
        common_crawl_mode=common_crawl_mode,
        common_crawl_domain=common_crawl_domain,
        ai_overview_mode=ai_overview_mode,
        chatgpt_mode=chatgpt_mode,
        claude_mode=claude_mode,
        gemini_mode=gemini_mode,
    )

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # Serializes concurrent create attempts for this
                # project *and* this user (see docstring above) —
                # released automatically on commit/rollback since this
                # is the `_xact_` variant. Two separate locks, not one
                # combined key, because the two queued-count checks
                # below have different scopes (project-wide vs.
                # user-wide) and a lock only serializes callers who
                # pass the exact same key — a single project-keyed
                # lock cannot also protect the user-wide count against
                # two different projects being hit concurrently by the
                # same user.
                #
                # `hashtextextended(id, seed)` is used for both so a
                # project id and a user id that happen to produce the
                # same raw hash can never collide into the same lock
                # key — `seed` (the second argument) gives each
                # namespace ("0" for project, "1" for user) its own
                # otherwise-identical hash space, exactly the way this
                # module already keys on a single namespace for the
                # project-only lock before this change.
                #
                # Always acquired in this fixed order (project, then
                # user) by every caller, with no code path anywhere in
                # this module acquiring them in the reverse order —
                # that fixed global ordering is what rules out a
                # deadlock between two transactions each waiting on a
                # lock the other already holds (the classic circular-
                # wait precondition for deadlock can't arise when
                # every transaction takes locks in the same order).
                cur.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (project_id,),
                )
                cur.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 1))",
                    (created_by_user_id,),
                )

                existing = _fetch_existing_job_by_idempotency_key(
                    cur,
                    project_id=project_id,
                    created_by_user_id=created_by_user_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    existing_id, existing_status, existing_snapshot = existing
                    if existing_snapshot != canonical_input:
                        raise AnalysisJobCreateConflictError(str(existing_id))
                    return AnalysisJobCreateResult(
                        analysis_run_id=str(existing_id),
                        status=existing_status,
                        created=False,
                    )

                cur.execute(
                    "select count(*) from analysis_runs where project_id = %s and status = 'queued'",
                    (project_id,),
                )
                if cur.fetchone()[0] >= max_queued_per_project:
                    raise AnalysisJobLimitExceededError(
                        "project", max_queued_per_project
                    )

                cur.execute(
                    "select count(*) from analysis_runs where created_by_user_id = %s and status = 'queued'",
                    (created_by_user_id,),
                )
                if cur.fetchone()[0] >= max_queued_per_user:
                    raise AnalysisJobLimitExceededError("user", max_queued_per_user)

                cur.execute(
                    "select id from brands where name = %s and project_id = %s order by created_at desc limit 1",
                    (canonical_input["brandName"], project_id),
                )
                brand_row = cur.fetchone()
                if brand_row is not None:
                    brand_id = brand_row[0]
                else:
                    cur.execute(
                        "insert into brands (name, project_id) values (%s, %s) returning id",
                        (canonical_input["brandName"], project_id),
                    )
                    brand_id = cur.fetchone()[0]

                cur.execute(
                    """
                    insert into analysis_runs
                        (brand_id, project_id, status, input_snapshot,
                         created_by_user_id, idempotency_key)
                    values (%s, %s, 'queued', %s, %s, %s)
                    returning id
                    """,
                    (
                        brand_id,
                        project_id,
                        Jsonb(canonical_input),
                        created_by_user_id,
                        idempotency_key,
                    ),
                )
                analysis_run_id = cur.fetchone()[0]

                cur.execute(
                    "insert into analysis_results (analysis_run_id, result_json) values (%s, %s)",
                    (analysis_run_id, Jsonb({})),
                )
            conn.commit()
    except (AnalysisJobCreateConflictError, AnalysisJobLimitExceededError):
        raise
    except Exception as exc:
        if UniqueViolation is not None and isinstance(exc, UniqueViolation):
            return _resolve_job_after_unique_violation(
                database_url,
                project_id=project_id,
                created_by_user_id=created_by_user_id,
                idempotency_key=idempotency_key,
                canonical_input=canonical_input,
            )
        logger.exception("Failed to create queued analysis job")
        raise AnalysisHistoryReadError("failed to create analysis job") from exc

    return AnalysisJobCreateResult(
        analysis_run_id=str(analysis_run_id), status="queued", created=True
    )


def get_analysis_job_status(analysis_run_id: str) -> dict[str, Any] | None:
    """Returns one job's lightweight status — backs GET
    /analysis-jobs/{id} (docs/40_async_analysis_jobs_design.md "7.2").
    Deliberately excludes result_json/meta_json, mirroring
    list_analysis_runs()'s existing "never includes result_json"
    discipline. Returns None when `analysis_run_id` doesn't exist, is
    malformed, or is soft-deleted — mirrors get_analysis_run()'s
    "soft-deleted is not found" handling (main.py turns this into a
    404).

    Raises AnalysisHistoryReadError on any connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    query = """
        select status, started_at, completed_at, error_message
        from analysis_runs
        where id = %s and deleted_at is null
    """

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (analysis_run_id,))
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to get analysis job status from DB")
        raise AnalysisHistoryReadError("failed to query analysis job") from exc

    if row is None:
        return None

    return {
        "id": analysis_run_id,
        "status": row[0],
        "startedAt": row[1].isoformat() if row[1] is not None else None,
        "completedAt": row[2].isoformat() if row[2] is not None else None,
        "errorMessage": row[3],
    }


def get_analysis_job_result(analysis_run_id: str) -> dict[str, Any] | None:
    """Returns one job's status plus result_json/meta_json *only* when
    status is 'completed'/'partial' — backs GET
    /analysis-jobs/{id}/result (docs/40_async_analysis_jobs_design.md
    "13.2"). For every other status (including the placeholder
    result_json='{}' Phase 1 writes at job creation — docs/40 "6.1"),
    `result`/`meta` are both None; callers must never surface that
    placeholder as if it were a real analysis result. Returns None
    when `analysis_run_id` doesn't exist, is malformed, or is
    soft-deleted (main.py turns this into a 404).

    Raises AnalysisHistoryReadError on any connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    query = """
        select ar.status, ar.error_message, res.result_json, res.meta_json
        from analysis_runs ar
        left join analysis_results res on res.analysis_run_id = ar.id
        where ar.id = %s and ar.deleted_at is null
        order by res.created_at desc
        limit 1
    """

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (analysis_run_id,))
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to get analysis job result from DB")
        raise AnalysisHistoryReadError("failed to query analysis job result") from exc

    if row is None:
        return None

    status, error_message, result_json, meta_json = row
    is_finished_with_result = status in ("completed", "partial")

    return {
        "id": analysis_run_id,
        "status": status,
        "errorMessage": error_message,
        "result": result_json if is_finished_with_result else None,
        "meta": meta_json if is_finished_with_result else None,
    }
