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
from datetime import datetime, timezone
from typing import Any, Literal

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
# installed. Captured once, here, at import time — every caller below
# does `if XViolation is not None and isinstance(exc, XViolation)`
# inside a broad `except Exception as exc:` rather than writing
# `except psycopg.errors.XViolation:` directly, specifically so tests
# can monkeypatch this module's `psycopg` name with a bare fake object
# (see tests/test_analysis_history_repository.py's _FakeReadPsycopg)
# without that fake object needing its own `.errors` namespace — a
# literal `except psycopg.errors.XViolation:` would raise AttributeError
# the moment any exception needed matching against it, once `psycopg`
# itself had been replaced.
UniqueViolation = psycopg.errors.UniqueViolation if psycopg is not None else None
ForeignKeyViolation = psycopg.errors.ForeignKeyViolation if psycopg is not None else None
NotNullViolation = psycopg.errors.NotNullViolation if psycopg is not None else None
CheckViolation = psycopg.errors.CheckViolation if psycopg is not None else None
InvalidTextRepresentation = (
    psycopg.errors.InvalidTextRepresentation if psycopg is not None else None
)

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
    project_id: str | None = None,
) -> AnalysisHistorySaveResult | None:
    """Best-effort save of one analysis run to Postgres.

    `project_id`, added by Task 6-B2
    (feature/sync-analyze-jwt-project-auth), is the caller's **already
    verified** project id — main.py's analyze() only ever passes one
    after confirming (via can_user_access_project()) that the caller's
    JWT actually belongs to that project. This function trusts it
    as-is and never re-derives or re-checks it; it must never be a raw,
    unverified value from the request body.

    - `project_id=None` (the default, used by every caller before this
      task and by the legacy/ANALYZE_AUTH_REQUIRED=false path):
      unchanged behavior — always resolves and saves to the fixed
      default project (organizations.slug='default',
      projects.slug='default'), exactly as before this parameter
      existed.
    - `project_id=<uuid>`: saves brand/analysis_run under that project
      instead. Brand lookup is scoped to `(name, project_id)` rather
      than name alone, so a same-named brand belonging to a *different*
      project is never silently reused across projects — this is the
      authenticated path's own project-isolation guarantee, independent
      of (and in addition to) the caller-side can_user_access_project()
      check.

    Returns None when:
    - DB persistence is not configured (DB_SAVE_ENABLED/DATABASE_URL —
      see services/db_settings.py); no connection is attempted.
    - The psycopg driver is not installed.
    - `project_id` is None and the default project doesn't exist yet
      (unchanged from before this parameter existed).
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
                if project_id is not None:
                    # Authenticated path (Task 6-B2): the caller
                    # already verified this exact project_id via
                    # can_user_access_project() — use it as-is, and
                    # scope the brand lookup to this project so a
                    # same-named brand from a different project is
                    # never silently reused.
                    target_project_id = project_id
                    cur.execute(
                        "select id from brands where name = %s and project_id = %s "
                        "order by created_at desc limit 1",
                        (brand_name, target_project_id),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        brand_id = row[0]
                    else:
                        cur.execute(
                            """
                            insert into brands (name, canonical_domain, project_id)
                            values (%s, %s, %s)
                            returning id
                            """,
                            (brand_name, canonical_domain, target_project_id),
                        )
                        brand_id = cur.fetchone()[0]
                else:
                    # Legacy/anonymous path. default project
                    # (organizations/projects with slug='default', see
                    # backend/migrations/002_add_organizations_projects.sql)
                    # is required for the project_id columns below. If
                    # it doesn't exist yet (e.g. migration 002 hasn't
                    # been applied to this database), skip the save
                    # entirely rather than writing new brands/
                    # analysis_runs rows with no project_id — see
                    # docs/28_supabase_auth_rls_migration_design.md
                    # "21. 本番適用状況" for why this is preferred over
                    # saving without a project_id.
                    target_project_id = get_default_project_id(cur)
                    if target_project_id is None:
                        logger.warning(
                            "default project (organizations.slug='default', "
                            "projects.slug='default') not found; skipping analysis history save"
                        )
                        return None

                    # Brand: reuse an existing row scoped to the
                    # default project (or a legacy project_id IS NULL
                    # row, which gets backfilled below) if one exists,
                    # otherwise create one — see
                    # docs/19_minimum_db_migration_design.md "5. brands
                    # テーブル案", which explicitly says not to enforce
                    # strict dedup here.
                    #
                    # Fixed by Task 7 (feature/sync-analyze-jwt-project-auth,
                    # "匿名モードのbrand/project整合性修正"): this lookup
                    # used to match on `name` alone, with no project
                    # scoping at all — a same-named brand already
                    # belonging to a *different*, non-default project
                    # (e.g. one created via the authenticated path
                    # above) could be silently reused here, while the
                    # new analysis_runs row was still stamped with
                    # `target_project_id` (the default project) —
                    # leaving the run's own brand pointing at a
                    # different project than the run itself. The fixed
                    # WHERE clause mirrors the authenticated path's own
                    # project-isolation guarantee: only a brand already
                    # in the default project, or one not yet claimed by
                    # any project, is ever reused here. Existing rows
                    # are never deleted or moved by this fix — a brand
                    # already (incorrectly) shared this way before this
                    # fix shipped is left exactly as it is; see this
                    # task's completion report for what that means for
                    # already-saved data.
                    cur.execute(
                        "select id, project_id from brands where name = %s "
                        "and (project_id = %s or project_id is null) "
                        "order by created_at desc limit 1",
                        (brand_name, target_project_id),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        brand_id, brand_project_id = row
                        if brand_project_id is None:
                            cur.execute(
                                "update brands set project_id = %s where id = %s",
                                (target_project_id, brand_id),
                            )
                    else:
                        cur.execute(
                            """
                            insert into brands (name, canonical_domain, project_id)
                            values (%s, %s, %s)
                            returning id
                            """,
                            (brand_name, canonical_domain, target_project_id),
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
                        target_project_id,
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


def _escape_like_pattern(term: str) -> str:
    """Escapes the three characters that are special to SQL
    LIKE/ILIKE (`\\`, `%`, `_`) so a search term containing one of them
    is matched literally rather than as an unintended wildcard. This is
    a correctness concern, not a SQL-injection one — every value below
    is still passed as its own parameterized placeholder, never
    interpolated into the query string, which is what actually
    prevents injection regardless of this escaping."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- AI観測状態フィルター (feature/history-ai-observation-filter) -------
#
# Lets GET /analysis-runs filter by whether each of the 4 AI
# providers (Google AI Overview, ChatGPT, Claude, Gemini) actually
# *mentioned* the brand — distinct from (and computed independently
# of) services/history_mode_summary.py's modeSummary, which only ever
# reports whether a provider *ran* (real/off/unavailable/unknown),
# never whether it mentioned the brand. Implemented entirely as SQL
# `case` expressions over the already-saved `analysis_results.
# meta_json`/`result_json` columns (Option 1 of this task's "判定元の
# データ" investigation) — no new column, no new table, no migration,
# no backfill. Evaluated inside PostgreSQL itself as part of the
# existing WHERE clause (before LIMIT/OFFSET), so this never pulls a
# full result_json back to the application layer just to filter — the
# per-page SELECT list below is unchanged.
#
# Every value embedded in the `case` expressions below (meta_json
# field names, platform label strings) is a hardcoded program
# constant — never user input — so it is safe to build these SQL
# fragments directly, without needing a bound parameter for each one
# (only the caller-supplied filter *value* being compared against is
# ever passed as a parameter, exactly like every other condition in
# this module).
#
# Five possible states per provider, mirroring this task's "1. 判定
# 仕様" exactly:
# - "mentioned": a real observation ran and the brand was mentioned.
# - "not_mentioned": a real observation ran and the brand was not
#   mentioned.
# - "off": the provider was not run at all this request.
# - "unavailable": the provider was run but the observation failed
#   (missing credentials, API error, etc.).
# - "unknown": can't be determined from this saved run's data — a
#   genuinely old saved run predating a given provider/field, a
#   missing/None meta_json, or (AI Overview only) mock data, which is
#   deliberately never treated as a real "mentioned"/"not_mentioned"
#   signal (this task's "AI Overviewについては、mockデータを実際の掲載
#   あり・なしとして扱わない").

_CHATGPT_PLATFORM_LABEL = "ChatGPT (OpenAI API)"
_CLAUDE_PLATFORM_LABEL = "Claude (Anthropic API)"
_GEMINI_PLATFORM_LABEL = "Gemini (Google API)"

# Matches either "Google AI Mode (DataForSEO Sandbox)" or "...Live)" —
# see services/ai_overview_provider.py's _ENVIRONMENT_PLATFORM_LABELS.
# Deliberately distinct from (and never matches) the mock fixture's
# "Google AI Overview" platform label (see
# services/ai_overview_provider.py's build_mock_ai_overview_comparison())
# — the whole point of this LIKE pattern is to only ever match a *real*
# DataForSEO-backed card, never the mock one.
_AI_OVERVIEW_PLATFORM_LIKE_PATTERN = "Google AI Mode (DataForSEO%"

_OBSERVATION_FILTER_VALUES = frozenset(
    {"mentioned", "not_mentioned", "off", "unavailable", "unknown"}
)

# Guards `jsonb_array_elements(res.result_json->'aiOverviewComparison')`
# against a hard SQL error on corrupted/unexpected data. A missing key
# or an actual JSON `null` already makes `jsonb_array_elements()`
# return zero rows on its own (no guard needed there) — but a
# *present*, non-null, non-array value (an object, string, number, or
# boolean; never written by this backend itself, but not something a
# raw database value can be trusted to rule out) makes
# `jsonb_array_elements()` raise `cannot extract elements from an
# object`/`...a scalar`, which aborts the *entire* query (every row,
# not just the malformed one) — confirmed by direct reproduction
# against a real PostgreSQL instance during this filter's review (see
# feature/history-ai-observation-filter's post-merge verification).
# Falling back to `'[]'::jsonb` for anything that isn't actually a
# JSON array keeps such a row landing in "unknown" (nothing readable
# matches an empty array) exactly like any other unreadable data,
# instead of 500ing the whole history list over one bad row.
_SAFE_AI_OVERVIEW_COMPARISON_ARRAY_SQL = (
    "case when jsonb_typeof(res.result_json->'aiOverviewComparison') = 'array' "
    "then res.result_json->'aiOverviewComparison' else '[]'::jsonb end"
)


def _mentioned_exists_clause(platform_match_sql: str, mentioned_literal: str) -> str:
    """Builds one `exists (...)` branch shared by
    _simple_provider_observation_state_sql()/
    _AI_OVERVIEW_OBSERVATION_STATE_SQL below. `platform_match_sql` is a
    complete `elem->>'platform' = '...'`/`... like '...'` condition;
    `mentioned_literal` is the literal text `'true'`/`'false'` to
    compare `elem->>'mentioned'` against *as text* — deliberately never
    `(elem->>'mentioned')::boolean`, which raises a hard SQL error
    (`invalid input syntax for type boolean`) for any saved value that
    isn't literally the string "true"/"false" (e.g. a missing field —
    `->>'mentioned'` on a dict with no such key is already NULL, which
    a text `=` comparison safely treats as "no match" instead of
    throwing — or, in principle, some other unexpected type on a
    corrupted row); confirmed by direct reproduction against a real
    PostgreSQL instance. A text comparison can never raise this error
    regardless of what's actually stored there.
    """
    return f"""exists (
                    select 1 from jsonb_array_elements({_SAFE_AI_OVERVIEW_COMPARISON_ARRAY_SQL}) elem
                    where {platform_match_sql} and elem->>'mentioned' = {mentioned_literal}
                )"""


def _simple_provider_observation_state_sql(meta_key: str, platform_label: str) -> str:
    """Builds the `case` expression for chatgpt/claude/gemini (all
    three share the same ChatGptStatus/ClaudeStatus/GeminiStatus
    vocabulary — exactly "real"/"off"/"unavailable", see
    backend/models.py) — `meta_key` is the AnalysisMeta field holding
    this provider's info dict (e.g. "chatgptProvider"); `platform_label`
    is the exact string services/<provider>_provider.py uses as that
    provider's `AIOverviewComparisonItem.platform` when it actually
    appends a card (see e.g. services/chatgpt_provider.py's
    CHATGPT_PLATFORM_LABEL).

    `status == "real"` is only ever recorded when the provider's own
    module actually appended a matching card to
    result_json.aiOverviewComparison (see e.g.
    services/chatgpt_provider.py's build_chatgpt_observation() —
    `item` is non-None exactly when status is "real") — so the inner
    `mentioned`/`not_mentioned` lookup below is expected to always find
    that card whenever `status = 'real'`; its own "unknown" fallback
    exists only to keep this expression total (defined for every row)
    in the rare case a saved run's result_json and meta_json disagree.
    A missing/None meta_json, or one predating this provider, leaves
    `status` NULL and falls through to the final "unknown" branch.
    """
    platform_match_sql = f"elem->>'platform' = '{platform_label}'"
    return f"""case
        when res.meta_json->'{meta_key}'->>'status' = 'off' then 'off'
        when res.meta_json->'{meta_key}'->>'status' = 'unavailable' then 'unavailable'
        when res.meta_json->'{meta_key}'->>'status' = 'real' then
            case
                when {_mentioned_exists_clause(platform_match_sql, "'true'")} then 'mentioned'
                when {_mentioned_exists_clause(platform_match_sql, "'false'")} then 'not_mentioned'
                else 'unknown'
            end
        else 'unknown'
    end"""


# AI Overview's own `case` expression is written out separately rather
# than reusing _simple_provider_observation_state_sql() above — unlike
# chatgpt/claude/gemini, its environment vocabulary includes "mock"
# (which must map to "unknown", never "mentioned"/"not_mentioned" —
# see this module's "AI観測状態フィルター" comment above) and its
# platform label varies by environment (Sandbox vs. Live), matched via
# _AI_OVERVIEW_PLATFORM_LIKE_PATTERN's `like` rather than `=`.
#
# `.replace('%', '%%')` below escapes the LIKE pattern's literal `%`
# for psycopg's own placeholder parser, which otherwise mistakes a
# lone `%` anywhere in the query text (not just actual `%s`-style
# placeholders) for a malformed one, regardless of it being inside a
# SQL string literal — this has nothing to do with the `_escape_like_pattern()`
# used elsewhere in this module for a *caller-supplied* search term;
# `_AI_OVERVIEW_PLATFORM_LIKE_PATTERN` is a fixed program constant.
#
# `environment` (added after `mode`/`status` — see backend/models.py's
# AIOverviewProviderInfo docstring) is preferred when present; a
# legacy saved run with no `environment` field but `mode = 'off'`
# falls back to "off" (the one case that can still be read
# unambiguously without it), and anything else with no `environment`
# falls back to "unknown" — a narrower fallback than
# services/history_mode_summary.py's own `_resolve_ai_overview_value()`,
# which is acceptable here: this task's "過去履歴の形式差異にも対応し、
# 判定できないデータはunknownとする" explicitly sanctions "unknown" for
# ambiguous legacy data.
_AI_OVERVIEW_PLATFORM_MATCH_SQL = (
    f"elem->>'platform' like '{_AI_OVERVIEW_PLATFORM_LIKE_PATTERN.replace('%', '%%')}'"
)

_AI_OVERVIEW_OBSERVATION_STATE_SQL = f"""case
    when res.meta_json->'aiOverviewProvider'->>'environment' = 'off' then 'off'
    when res.meta_json->'aiOverviewProvider'->>'environment' = 'unavailable' then 'unavailable'
    when res.meta_json->'aiOverviewProvider'->>'environment' = 'mock' then 'unknown'
    when res.meta_json->'aiOverviewProvider'->>'environment' in ('sandbox', 'live') then
        case
            when {_mentioned_exists_clause(_AI_OVERVIEW_PLATFORM_MATCH_SQL, "'true'")} then 'mentioned'
            when {_mentioned_exists_clause(_AI_OVERVIEW_PLATFORM_MATCH_SQL, "'false'")} then 'not_mentioned'
            else 'unknown'
        end
    when res.meta_json->'aiOverviewProvider'->>'mode' = 'off' then 'off'
    else 'unknown'
end"""

_CHATGPT_OBSERVATION_STATE_SQL = _simple_provider_observation_state_sql(
    "chatgptProvider", _CHATGPT_PLATFORM_LABEL
)
_CLAUDE_OBSERVATION_STATE_SQL = _simple_provider_observation_state_sql(
    "claudeProvider", _CLAUDE_PLATFORM_LABEL
)
_GEMINI_OBSERVATION_STATE_SQL = _simple_provider_observation_state_sql(
    "geminiProvider", _GEMINI_PLATFORM_LABEL
)


# Builds a `tags` JSON array for one run as a SELECT-list expression —
# a correlated subquery, never a `from`-clause JOIN, so a run with N
# tags still contributes exactly one output row (feature/history-
# tags-categories; see list_analysis_runs()/get_analysis_run()'s
# docstrings for why this matters for the stable sort/pagination).
# `coalesce(..., '[]'::jsonb)` so a tagless run gets an empty array
# rather than SQL NULL.
_TAGS_JSON_SUBQUERY_SQL = """coalesce(
            (
                select jsonb_agg(jsonb_build_object('id', t.id, 'projectId', t.project_id, 'name', t.name) order by t.name)
                from analysis_run_tags art
                join tags t on t.id = art.tag_id
                where art.analysis_run_id = ar.id
            ),
            '[]'::jsonb
        ) as tags_json"""


def _build_history_filter_conditions(
    *,
    brand: str | None,
    status: str | None,
    project_ids: list[str] | None,
    search: str | None,
    important: bool | None,
    started_from: datetime | None,
    started_to: datetime | None,
    ai_overview_observation: str | None = None,
    chatgpt_observation: str | None = None,
    claude_observation: str | None = None,
    gemini_observation: str | None = None,
    favorite: bool | None = None,
    tag_ids: list[str] | None = None,
    category_id: str | None = None,
    uncategorized_only: bool = False,
) -> tuple[list[str], list[Any], bool]:
    """Builds the shared WHERE-clause conditions/params for both
    list_analysis_runs() and count_analysis_runs() below, so the two
    can never drift apart (the count must reflect exactly the same
    filter as the page being counted) — see
    docs/40_async_analysis_jobs_design.md-adjacent
    feature/history-server-side-search-pagination.

    `search` matches brand name, `brands.canonical_domain`, or the raw
    `urls` recorded in `input_snapshot` (a crude but effective
    substring match over that JSON array's text form — covers the
    common case of searching for a domain/hostname that appears
    somewhere in one of the saved URLs), case-insensitively (`ilike`)
    and with LIKE metacharacters in the term itself escaped (see
    _escape_like_pattern() above) so a literal `%`/`_` in a brand name
    can never behave as an unintended wildcard. Every value is bound
    as its own parameterized placeholder — never string-interpolated
    into the query — which is what actually prevents SQL injection
    here (the escaping above is a separate, LIKE-specific correctness
    concern).

    `important=True` adds `ar.is_important`; `False` or `None` (the
    default, "all") adds no condition at all — there is deliberately
    no "important=False" filter mode, matching the existing
    frontend's "すべて/重要のみ" 2-way toggle (not a 3-way one).

    `favorite` behaves identically to `important` above but on the
    independent `ar.is_favorite` column (backend/migrations/
    007_add_is_favorite_to_analysis_runs.sql,
    feature/history-favorite-flag) — same `True`-only-adds-a-condition
    2-way-toggle semantics, combined with every other filter here
    (including `important` itself) as AND.

    `started_from`/`started_to` filter on `coalesce(ar.started_at,
    ar.created_at)` — the exact same fallback the existing display
    layer already uses for a run with no `started_at`.
    `started_from` is an inclusive lower bound, `started_to` an
    *exclusive* upper bound — callers wanting "through end of a given
    calendar day" pass the start of the *next* day as `started_to`
    (see app/lib/analysis-history.ts's jstDateStringToRangeBoundary()
    on the frontend side, which is where the JST calendar-date ->
    precise instant conversion happens; this function only ever
    compares already-resolved, timezone-aware instants).

    `ai_overview_observation`/`chatgpt_observation`/
    `claude_observation`/`gemini_observation` each filter on one of
    "mentioned"/"not_mentioned"/"off"/"unavailable"/"unknown" (see this
    module's "AI観測状態フィルター" section above) — independent of each
    other and combined with every other condition here as AND, exactly
    like `important`/the date range. Each references `res.meta_json`/
    `res.result_json` (the `analysis_results` row joined in as `res`),
    so the third return value is `True` whenever at least one of these
    four is set — callers (count_analysis_runs() below) use it to
    decide whether they need to join `analysis_results` at all, to
    avoid that extra join's cost on every call that doesn't use this
    feature.

    `tag_ids` (feature/history-tags-categories): OR-matches any run
    that has *at least one* of the given tags, via an `exists (...)`
    correlated subquery against `analysis_run_tags` — never a JOIN in
    the main query's FROM clause, which would multiply a row once per
    matching tag and corrupt both the count and the stable
    pagination. `category_id`/`uncategorized_only` filter the plain
    `ar.category_id` column directly (no join needed at all, since a
    run has at most one category) — `uncategorized_only=True` means
    `ar.category_id is null`; callers must never pass both
    `category_id` and `uncategorized_only=True` together (main.py
    rejects that combination with 400 before it reaches here).
    """
    conditions: list[str] = ["ar.deleted_at is null"]
    params: list[Any] = []
    needs_results_join = False

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
    if search is not None and search.strip():
        pattern = f"%{_escape_like_pattern(search.strip())}%"
        conditions.append(
            "(b.name ilike %s escape '\\' "
            "or b.canonical_domain ilike %s escape '\\' "
            "or (ar.input_snapshot->>'urls') ilike %s escape '\\')"
        )
        params.extend([pattern, pattern, pattern])
    if important:
        conditions.append("ar.is_important")
    if favorite:
        conditions.append("ar.is_favorite")
    if started_from is not None:
        conditions.append("coalesce(ar.started_at, ar.created_at) >= %s")
        params.append(started_from)
    if started_to is not None:
        conditions.append("coalesce(ar.started_at, ar.created_at) < %s")
        params.append(started_to)
    if ai_overview_observation is not None:
        conditions.append(f"({_AI_OVERVIEW_OBSERVATION_STATE_SQL}) = %s")
        params.append(ai_overview_observation)
        needs_results_join = True
    if chatgpt_observation is not None:
        conditions.append(f"({_CHATGPT_OBSERVATION_STATE_SQL}) = %s")
        params.append(chatgpt_observation)
        needs_results_join = True
    if claude_observation is not None:
        conditions.append(f"({_CLAUDE_OBSERVATION_STATE_SQL}) = %s")
        params.append(claude_observation)
        needs_results_join = True
    if gemini_observation is not None:
        conditions.append(f"({_GEMINI_OBSERVATION_STATE_SQL}) = %s")
        params.append(gemini_observation)
        needs_results_join = True
    if tag_ids:
        placeholders = ", ".join(["%s"] * len(tag_ids))
        conditions.append(
            f"""exists (
                select 1 from analysis_run_tags art
                where art.analysis_run_id = ar.id and art.tag_id in ({placeholders})
            )"""
        )
        params.extend(tag_ids)
    if uncategorized_only:
        conditions.append("ar.category_id is null")
    elif category_id is not None:
        conditions.append("ar.category_id = %s")
        params.append(category_id)

    return conditions, params, needs_results_join


def count_analysis_runs(
    *,
    brand: str | None = None,
    status: str | None = None,
    project_ids: list[str] | None = None,
    search: str | None = None,
    important: bool | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    ai_overview_observation: str | None = None,
    chatgpt_observation: str | None = None,
    claude_observation: str | None = None,
    gemini_observation: str | None = None,
    favorite: bool | None = None,
    tag_ids: list[str] | None = None,
    category_id: str | None = None,
    uncategorized_only: bool = False,
) -> int:
    """Counts how many rows list_analysis_runs() would return across
    *every* page for the exact same filter (same parameters, minus
    limit/offset/sort, which don't affect a count) — backs
    AnalysisRunListResponse.total. Deliberately a single lightweight
    `count(*)` query, joined only to `brands` (needed for the `search`/
    `brand` conditions) by default, never to `analysis_results` — the
    per-page query's heavier `left join` to fetch `visibility_score`/
    `meta_json` is unnecessary for a count and would cost more without
    changing the result (see this task's "件数取得による過度なDB負荷を
    避ける"). `analysis_results` is joined in too, but *only* when at
    least one of `ai_overview_observation`/`chatgpt_observation`/
    `claude_observation`/`gemini_observation` is actually set (see
    _build_history_filter_conditions()'s third return value) — every
    existing caller that doesn't use this feature keeps the original,
    lighter query unchanged.

    Raises AnalysisHistoryReadError on any connection/query failure.
    Does not itself check READ_HISTORY_ENABLED — same contract as
    list_analysis_runs().
    """
    if project_ids is not None and len(project_ids) == 0:
        return 0

    database_url = _require_connectable()

    conditions, params, needs_results_join = _build_history_filter_conditions(
        brand=brand,
        status=status,
        project_ids=project_ids,
        search=search,
        important=important,
        started_from=started_from,
        started_to=started_to,
        ai_overview_observation=ai_overview_observation,
        chatgpt_observation=chatgpt_observation,
        claude_observation=claude_observation,
        gemini_observation=gemini_observation,
        favorite=favorite,
        tag_ids=tag_ids,
        category_id=category_id,
        uncategorized_only=uncategorized_only,
    )
    where_clause = f"where {' and '.join(conditions)}"
    results_join = (
        "left join analysis_results res on res.analysis_run_id = ar.id"
        if needs_results_join
        else ""
    )
    query = f"""
        select count(*)
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        {results_join}
        {where_clause}
    """

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                (total,) = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to count analysis runs from DB")
        raise AnalysisHistoryReadError("failed to query analysis history") from exc

    return int(total)


def list_analysis_runs(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    brand: str | None = None,
    status: str | None = None,
    project_ids: list[str] | None = None,
    search: str | None = None,
    important: bool | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    ai_overview_observation: str | None = None,
    chatgpt_observation: str | None = None,
    claude_observation: str | None = None,
    gemini_observation: str | None = None,
    favorite: bool | None = None,
    tag_ids: list[str] | None = None,
    category_id: str | None = None,
    uncategorized_only: bool = False,
    sort: Literal["newest", "oldest"] = "newest",
) -> list[dict[str, Any]]:
    """Returns saved analysis run summaries (brands ⋈ analysis_runs ⋈
    analysis_results), newest-or-oldest-first per `sort` — see
    docs/20_analysis_history_read_api_design.md "5. GET /analysis-runs
    の設計案" and feature/history-server-side-search-pagination's
    extension of it (search/important/date-range/sort, all applied in
    PostgreSQL itself rather than over just the current page — see
    that task for why: the previous client-side-only filtering could
    never find a match past the first fetched page). Deliberately
    never includes result_json (see that section's "返さないもの").
    Each item's `sourceUrls` is derived from `analysis_runs.input_snapshot`
    (see _extract_source_urls() above) — added so the frontend history
    list can search by domain even though `canonicalDomain` (from
    `brands.canonical_domain`) is never actually populated by
    save_analysis_history() today. Always excludes a soft-deleted run
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

    `search`/`important`/`started_from`/`started_to`/
    `ai_overview_observation`/`chatgpt_observation`/`claude_observation`/
    `gemini_observation`/`favorite`/`tag_ids`/`category_id`/
    `uncategorized_only` are documented on
    _build_history_filter_conditions() above, which this function
    shares verbatim with count_analysis_runs() so the two can never
    disagree about what matches.

    Each item's `tags`/`category` (feature/history-tags-categories)
    are populated via a correlated subquery (tags, aggregated as a
    JSON array per run) and a plain `left join categories` (a run has
    at most one category, so this can never multiply a row) — neither
    is part of the filter above, which uses its own, separate
    `exists(...)`/plain-column conditions specifically so filtering
    and display can never interact with the stable sort/pagination
    below.

    The `order by` uses `ar.id` as a secondary, same-direction sort key
    after the primary `coalesce(started_at, created_at)` key — without
    a deterministic tie-breaker, PostgreSQL does not guarantee a
    stable row order for ties across separate paginated queries (two
    rows saved in the same transaction can easily share an identical
    timestamp), which would otherwise risk a row appearing on two
    pages or on none as the caller pages through results (this task's
    "同日時の場合の安定ソート").

    Raises AnalysisHistoryReadError on any connection/query failure.
    Does not itself check READ_HISTORY_ENABLED — callers must call
    services.db_settings.is_history_read_enabled() first.
    """
    if project_ids is not None and len(project_ids) == 0:
        return []

    database_url = _require_connectable()

    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    conditions, params, _ = _build_history_filter_conditions(
        brand=brand,
        status=status,
        project_ids=project_ids,
        search=search,
        important=important,
        started_from=started_from,
        started_to=started_to,
        ai_overview_observation=ai_overview_observation,
        chatgpt_observation=chatgpt_observation,
        claude_observation=claude_observation,
        gemini_observation=gemini_observation,
        favorite=favorite,
        tag_ids=tag_ids,
        category_id=category_id,
        uncategorized_only=uncategorized_only,
    )
    where_clause = f"where {' and '.join(conditions)}"
    order_direction = "asc" if sort == "oldest" else "desc"

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
            ar.is_important,
            ar.is_favorite,
            c.id,
            c.project_id,
            c.name,
            {_TAGS_JSON_SUBQUERY_SQL}
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        left join analysis_results res on res.analysis_run_id = ar.id
        left join categories c on c.id = ar.category_id
        {where_clause}
        order by coalesce(ar.started_at, ar.created_at) {order_direction}, ar.id {order_direction}
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
            # analysis_runs.is_favorite (backend/migrations/
            # 007_add_is_favorite_to_analysis_runs.sql) — independent
            # of isImportant above (feature/history-favorite-flag).
            "isFavorite": bool(row[12]),
            # analysis_runs.category_id, joined to categories for its
            # name (feature/history-tags-categories). None ("未分類")
            # when category_id is null or points at a deleted
            # category (the latter can't actually happen once
            # migration 008's ON DELETE SET NULL(category_id) runs,
            # but a plain left join degrades the same way regardless).
            "category": (
                {"id": str(row[13]), "projectId": str(row[14]), "name": row[15]}
                if row[13] is not None
                else None
            ),
            # Every tag currently attached to this run, via the
            # correlated subquery above — already a list of plain
            # dicts (jsonb_agg/jsonb_build_object), never SQL NULL.
            "tags": row[16],
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

    query = f"""
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
            ar.is_important,
            ar.is_favorite,
            c.id,
            c.project_id,
            c.name,
            {_TAGS_JSON_SUBQUERY_SQL}
        from analysis_runs ar
        join brands b on b.id = ar.brand_id
        left join analysis_results res on res.analysis_run_id = ar.id
        left join categories c on c.id = ar.category_id
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
        # analysis_runs.is_favorite (backend/migrations/
        # 007_add_is_favorite_to_analysis_runs.sql) — independent of
        # isImportant above (feature/history-favorite-flag).
        "isFavorite": bool(row[13]),
        # Same fields/semantics as list_analysis_runs()'s "category"/
        # "tags" above (feature/history-tags-categories).
        "category": (
            {"id": str(row[14]), "projectId": str(row[15]), "name": row[16]}
            if row[14] is not None
            else None
        ),
        "tags": row[17],
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


def set_analysis_run_favorite(analysis_run_id: str, *, is_favorite: bool) -> bool:
    """Sets one analysis_runs row's `is_favorite` flag — see
    backend/migrations/007_add_is_favorite_to_analysis_runs.sql. Backs
    PATCH /analysis-runs/{id}/favorite. Mirrors
    set_analysis_run_important() above exactly (same soft-delete
    handling, same unscoped-by-project contract, same error handling)
    — `is_favorite` and `is_important` are independent columns, each
    toggled by its own endpoint without touching the other.

    Returns True when a row was updated, False when `analysis_run_id`
    doesn't exist, is malformed, or is soft-deleted (`deleted_at is not
    null`) — main.py turns False into a 404, same as
    set_analysis_run_important().

    Deliberately unscoped by project, exactly like
    set_analysis_run_important() above — main.py's PATCH endpoint is
    responsible for authorizing the caller against `analysis_run_id`
    *before* calling this.

    Raises AnalysisHistoryReadError on any connection/query failure —
    reuses this module's existing read-error type. This includes the
    case where migration 007 hasn't been applied yet (the
    `is_favorite` column doesn't exist) — surfaces to the API caller
    as the same 503 every other DB failure does.
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
                    set is_favorite = %s
                    where id = %s and deleted_at is null
                    returning id
                    """,
                    (is_favorite, analysis_run_id),
                )
                updated = cur.fetchone() is not None
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to update analysis run favorite flag")
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


# --- Tags / categories (feature/history-tags-categories) -----------------
#
# See backend/migrations/008_add_tags_and_categories.sql for the full
# schema/constraint design this section relies on: project-shared
# `tags`/`categories` tables, a many-to-many `analysis_run_tags` join
# table, and `analysis_runs.category_id` (nullable, "未分類" = null).
# Every write here relies on a real-PostgreSQL constraint to do the
# actual safety-critical work rather than re-deriving it in Python:
#
# - `uq_tags_project_name_ci`/`uq_categories_project_name_ci` (UNIQUE
#   index on `(project_id, lower(btrim(name)))`) reject a duplicate
#   name — caught here as psycopg.errors.UniqueViolation.
# - `chk_tags_name_length`/`chk_categories_name_length` reject an
#   empty/over-length name — caught as psycopg.errors.CheckViolation.
# - The composite FKs on `analysis_run_tags`/`analysis_runs.category_id`
#   reject attaching a tag/category from a different project than the
#   run's own `project_id` — caught as
#   psycopg.errors.ForeignKeyViolation (or InvalidTextRepresentation
#   for a malformed, non-UUID id, which never matches any row).
# - `chk_analysis_runs_category_requires_project` rejects setting a
#   category on a run whose `project_id` is null — caught as a
#   distinct CheckViolation, surfaced as CategoryRequiresProjectError
#   rather than CategoryNotAssignableError, since the problem here is
#   the *run*, not the category.
#
# None of these checks are re-implemented in Python — this module only
# ever translates the DB's own rejection into a specific exception
# type main.py can map to the right HTTP status, exactly the same
# "let the constraint be the source of truth" approach
# create_queued_analysis_run() already uses for its own unique index.


class TagNameConflictError(Exception):
    """Raised by create_tag()/rename_tag() when the (project_id,
    case/whitespace-insensitive name) already exists in that project
    — backs the `uq_tags_project_name_ci` unique index. main.py turns
    this into 409."""


class TagNameInvalidError(Exception):
    """Raised by create_tag()/rename_tag() when `name` is empty
    (after trimming) or over 100 characters — backs
    `chk_tags_name_length`. main.py turns this into 400."""


class CategoryNameConflictError(Exception):
    """Mirrors TagNameConflictError for categories
    (`uq_categories_project_name_ci`)."""


class CategoryNameInvalidError(Exception):
    """Mirrors TagNameInvalidError for categories
    (`chk_categories_name_length`)."""


class AnalysisRunStatusConflictError(Exception):
    """Raised by attach_tag_to_analysis_run()/
    detach_tag_from_analysis_run()/set_analysis_run_category() when
    the target run's status is 'queued' or 'running' — this task's
    explicit requirement that tag/category edits be blocked at the
    backend for a job still in progress, not just hidden by the
    frontend (unlike set_analysis_run_important()/
    set_analysis_run_favorite() above, which impose no backend status
    restriction at all — tags/categories are deliberately stricter
    here). main.py turns this into 409. Carries the offending status
    for the error message."""

    def __init__(self, status: str):
        super().__init__(f"analysis run status {status!r} does not allow tag/category edits")
        self.status = status


class TagNotAssignableError(Exception):
    """Raised by attach_tag_to_analysis_run() when `tag_id` doesn't
    exist, is malformed, or belongs to a different project than the
    run — all three collapse into this one exception (never
    distinguished) for the same existence-leak-avoidance reason
    services.project_access's helpers already follow. main.py turns
    this into 404."""


class CategoryNotAssignableError(Exception):
    """Mirrors TagNotAssignableError for
    set_analysis_run_category()."""


class CategoryRequiresProjectError(Exception):
    """Raised by set_analysis_run_category() when the target run's
    `project_id` is null — backs
    `chk_analysis_runs_category_requires_project`. Distinct from
    CategoryNotAssignableError: the category itself may be perfectly
    valid, the run simply has no project to scope it to. main.py turns
    this into 400."""


def _raise_for_name_write_error(
    exc: Exception, *, conflict_error: type[Exception], invalid_error: type[Exception]
) -> None:
    """Shared by create_tag()/rename_tag()/create_category()/
    rename_category() — translates a UniqueViolation/CheckViolation
    raised by the DB into the matching domain-specific exception.
    Returns normally (does nothing) for anything else, so the caller's
    own broad `except Exception` handler runs next."""
    if UniqueViolation is not None and isinstance(exc, UniqueViolation):
        raise conflict_error() from exc
    if CheckViolation is not None and isinstance(exc, CheckViolation):
        raise invalid_error() from exc


def create_tag(*, project_id: str, name: str) -> dict[str, Any]:
    """Creates one project-shared tag. Raises TagNameConflictError on
    a case/whitespace-insensitive duplicate within `project_id`,
    TagNameInvalidError for an empty/over-100-character name, and
    AnalysisHistoryReadError on any other connection/query failure
    (including `project_id` not referencing a real project — main.py
    is expected to have already checked this via
    services.project_access.can_user_access_project() before calling,
    so that case is treated as an unexpected failure here, not a
    documented outcome).
    """
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into tags (project_id, name) values (%s, %s) "
                    "returning id, project_id, name",
                    (project_id, name),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        _raise_for_name_write_error(
            exc, conflict_error=TagNameConflictError, invalid_error=TagNameInvalidError
        )
        logger.exception("Failed to create tag")
        raise AnalysisHistoryReadError("failed to create tag") from exc

    return {"id": str(row[0]), "projectId": str(row[1]), "name": row[2]}


def list_tags(
    *, project_ids: list[str] | None = None, project_id: str | None = None
) -> list[dict[str, Any]]:
    """Lists tags, newest-name-first... actually alphabetical by name
    (a small, flat list — there's no pagination concern here, unlike
    list_analysis_runs()). `project_ids` restricts to an accessible
    set (JWT mode — an explicit `[]` short-circuits to `[]` without
    touching the DB, same convention as list_analysis_runs());
    `project_id` optionally narrows further to one specific project
    (works in either mode, e.g. a caller who only wants one project's
    tags). Both `None` means "every tag in every project" — only ever
    reached in HISTORY_READ_TOKEN mode, mirroring
    list_analysis_runs()'s own `project_ids=None` meaning.
    """
    if project_ids is not None and len(project_ids) == 0:
        return []

    database_url = _require_connectable()

    conditions: list[str] = []
    params: list[Any] = []
    if project_ids is not None:
        placeholders = ", ".join(["%s"] * len(project_ids))
        conditions.append(f"project_id in ({placeholders})")
        params.extend(project_ids)
    if project_id is not None:
        conditions.append("project_id = %s")
        params.append(project_id)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""

    query = f"select id, project_id, name from tags {where_clause} order by name"

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("Failed to list tags")
        raise AnalysisHistoryReadError("failed to list tags") from exc

    return [{"id": str(r[0]), "projectId": str(r[1]), "name": r[2]} for r in rows]


def rename_tag(tag_id: str, *, name: str) -> dict[str, Any] | None:
    """Renames one tag — the join table (`analysis_run_tags`) is keyed
    by `tag_id`, never by name, so every existing association survives
    a rename untouched. Returns None for a malformed/nonexistent
    `tag_id`. Raises TagNameConflictError/TagNameInvalidError the same
    way create_tag() does.
    """
    try:
        uuid.UUID(tag_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update tags set name = %s, updated_at = now() where id = %s "
                    "returning id, project_id, name",
                    (name, tag_id),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        _raise_for_name_write_error(
            exc, conflict_error=TagNameConflictError, invalid_error=TagNameInvalidError
        )
        logger.exception("Failed to rename tag")
        raise AnalysisHistoryReadError("failed to rename tag") from exc

    if row is None:
        return None
    return {"id": str(row[0]), "projectId": str(row[1]), "name": row[2]}


def delete_tag(tag_id: str) -> bool:
    """Deletes one tag — `analysis_run_tags`' composite FK to `tags`
    is `on delete cascade`, so every association row referencing this
    tag is removed along with it; `analysis_runs` itself is never
    touched (this task's "タグ削除時に分析履歴本体を削除しない").
    Returns False for a malformed/nonexistent `tag_id`.
    """
    try:
        uuid.UUID(tag_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from tags where id = %s returning id", (tag_id,))
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to delete tag")
        raise AnalysisHistoryReadError("failed to delete tag") from exc

    return row is not None


def create_category(*, project_id: str, name: str) -> dict[str, Any]:
    """Mirrors create_tag() exactly, one table swapped."""
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into categories (project_id, name) values (%s, %s) "
                    "returning id, project_id, name",
                    (project_id, name),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        _raise_for_name_write_error(
            exc, conflict_error=CategoryNameConflictError, invalid_error=CategoryNameInvalidError
        )
        logger.exception("Failed to create category")
        raise AnalysisHistoryReadError("failed to create category") from exc

    return {"id": str(row[0]), "projectId": str(row[1]), "name": row[2]}


def list_categories(
    *, project_ids: list[str] | None = None, project_id: str | None = None
) -> list[dict[str, Any]]:
    """Mirrors list_tags() exactly, one table swapped."""
    if project_ids is not None and len(project_ids) == 0:
        return []

    database_url = _require_connectable()

    conditions: list[str] = []
    params: list[Any] = []
    if project_ids is not None:
        placeholders = ", ".join(["%s"] * len(project_ids))
        conditions.append(f"project_id in ({placeholders})")
        params.extend(project_ids)
    if project_id is not None:
        conditions.append("project_id = %s")
        params.append(project_id)
    where_clause = f"where {' and '.join(conditions)}" if conditions else ""

    query = f"select id, project_id, name from categories {where_clause} order by name"

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
    except Exception as exc:
        logger.exception("Failed to list categories")
        raise AnalysisHistoryReadError("failed to list categories") from exc

    return [{"id": str(r[0]), "projectId": str(r[1]), "name": r[2]} for r in rows]


def rename_category(category_id: str, *, name: str) -> dict[str, Any] | None:
    """Mirrors rename_tag() exactly — `analysis_runs.category_id` is
    keyed by id, so a rename never disturbs which runs are in this
    category."""
    try:
        uuid.UUID(category_id)
    except (ValueError, AttributeError, TypeError):
        return None

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update categories set name = %s, updated_at = now() where id = %s "
                    "returning id, project_id, name",
                    (name, category_id),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        _raise_for_name_write_error(
            exc, conflict_error=CategoryNameConflictError, invalid_error=CategoryNameInvalidError
        )
        logger.exception("Failed to rename category")
        raise AnalysisHistoryReadError("failed to rename category") from exc

    if row is None:
        return None
    return {"id": str(row[0]), "projectId": str(row[1]), "name": row[2]}


def delete_category(category_id: str) -> bool:
    """Deletes one category — `analysis_runs.category_id`'s composite
    FK is `on delete set null (category_id)`, so every run in this
    category becomes "未分類" (category_id -> null) atomically;
    `analysis_runs` rows themselves are never touched. Returns False
    for a malformed/nonexistent `category_id`.
    """
    try:
        uuid.UUID(category_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from categories where id = %s returning id", (category_id,)
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to delete category")
        raise AnalysisHistoryReadError("failed to delete category") from exc

    return row is not None


def _get_analysis_run_status_for_edit(cur, analysis_run_id: str) -> str | None:
    """Shared by attach_tag_to_analysis_run()/
    detach_tag_from_analysis_run()/set_analysis_run_category() —
    looks up one non-soft-deleted run's status using an already-open
    cursor. Returns None for "doesn't exist or is soft-deleted" (the
    caller turns this into a False/404 result), otherwise the status
    string (the caller checks it against 'queued'/'running' itself,
    so this helper stays a plain lookup with no policy baked in)."""
    cur.execute(
        "select status from analysis_runs where id = %s and deleted_at is null",
        (analysis_run_id,),
    )
    row = cur.fetchone()
    return row[0] if row is not None else None


# Statuses for which this task explicitly requires the backend (not
# just the frontend) to refuse a tag/category edit — see
# AnalysisRunStatusConflictError's docstring above.
_STATUSES_BLOCKING_TAG_CATEGORY_EDITS = frozenset({"queued", "running"})


def attach_tag_to_analysis_run(analysis_run_id: str, tag_id: str) -> bool:
    """Attaches one tag to one run — idempotent (`on conflict ...
    do nothing`): attaching an already-attached tag is a no-op
    success, not an error.

    Returns False when `analysis_run_id` doesn't exist, is malformed,
    or is soft-deleted. Raises AnalysisRunStatusConflictError when the
    run's status is 'queued'/'running'. Raises TagNotAssignableError
    when `tag_id` doesn't exist, is malformed, or belongs to a
    different project than the run (the composite FK on
    `analysis_run_tags` rejects the INSERT in exactly this case — see
    this section's module docstring). Raises AnalysisHistoryReadError
    on any other connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                status = _get_analysis_run_status_for_edit(cur, analysis_run_id)
                if status is None:
                    return False
                if status in _STATUSES_BLOCKING_TAG_CATEGORY_EDITS:
                    raise AnalysisRunStatusConflictError(status)

                cur.execute(
                    """
                    insert into analysis_run_tags (analysis_run_id, tag_id, project_id)
                    select ar.id, %s, ar.project_id
                    from analysis_runs ar
                    where ar.id = %s
                    on conflict (analysis_run_id, tag_id) do nothing
                    """,
                    (tag_id, analysis_run_id),
                )
            conn.commit()
    except AnalysisRunStatusConflictError:
        raise
    except Exception as exc:
        if any(
            cls is not None and isinstance(exc, cls)
            for cls in (ForeignKeyViolation, NotNullViolation, InvalidTextRepresentation)
        ):
            raise TagNotAssignableError() from exc
        logger.exception("Failed to attach tag to analysis run")
        raise AnalysisHistoryReadError("failed to update analysis history") from exc

    return True


def detach_tag_from_analysis_run(analysis_run_id: str, tag_id: str) -> bool:
    """Detaches one tag from one run — idempotent: detaching a tag
    that was never attached (or already detached) is a no-op success,
    not an error, consistent with soft_delete_analysis_run()'s own
    "repeat is success" convention. Never validates `tag_id` beyond
    "is it a well-formed UUID" (deleting a nonexistent association row
    is always harmless).

    Returns False when `analysis_run_id` doesn't exist, is malformed,
    or is soft-deleted. Raises AnalysisRunStatusConflictError when the
    run's status is 'queued'/'running'. Raises
    AnalysisHistoryReadError on any other connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                status = _get_analysis_run_status_for_edit(cur, analysis_run_id)
                if status is None:
                    return False
                if status in _STATUSES_BLOCKING_TAG_CATEGORY_EDITS:
                    raise AnalysisRunStatusConflictError(status)

                try:
                    cur.execute(
                        "delete from analysis_run_tags where analysis_run_id = %s and tag_id = %s",
                        (analysis_run_id, tag_id),
                    )
                except Exception as exc:
                    if InvalidTextRepresentation is not None and isinstance(
                        exc, InvalidTextRepresentation
                    ):
                        # A malformed tag_id can never have been
                        # attached in the first place — detaching it
                        # is the same harmless no-op as detaching a
                        # well-formed but unattached tag_id. Caught
                        # here (inside the transaction) so the status
                        # check above still counts, and the
                        # transaction is explicitly rolled back before
                        # returning, since this connection's
                        # transaction is now aborted after the error.
                        conn.rollback()
                        return True
                    raise
            conn.commit()
    except AnalysisRunStatusConflictError:
        raise
    except Exception as exc:
        logger.exception("Failed to detach tag from analysis run")
        raise AnalysisHistoryReadError("failed to update analysis history") from exc

    return True


def set_analysis_run_category(analysis_run_id: str, category_id: str | None) -> bool:
    """Sets (or, with `category_id=None`, clears back to "未分類") one
    run's category.

    Returns False when `analysis_run_id` doesn't exist, is malformed,
    or is soft-deleted. Raises AnalysisRunStatusConflictError when the
    run's status is 'queued'/'running'. Raises
    CategoryNotAssignableError when `category_id` doesn't exist, is
    malformed, or belongs to a different project than the run (the
    composite FK `fk_analysis_runs_category_project` rejects the
    UPDATE in exactly this case) — never raised when `category_id` is
    None, since clearing a category is always allowed regardless of
    the run's project. Raises CategoryRequiresProjectError when
    `category_id` is not None but the run's own `project_id` is null
    (`chk_analysis_runs_category_requires_project`). Raises
    AnalysisHistoryReadError on any other connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return False

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                status = _get_analysis_run_status_for_edit(cur, analysis_run_id)
                if status is None:
                    return False
                if status in _STATUSES_BLOCKING_TAG_CATEGORY_EDITS:
                    raise AnalysisRunStatusConflictError(status)

                cur.execute(
                    "update analysis_runs set category_id = %s where id = %s",
                    (category_id, analysis_run_id),
                )
            conn.commit()
    except AnalysisRunStatusConflictError:
        raise
    except Exception as exc:
        if CheckViolation is not None and isinstance(exc, CheckViolation):
            raise CategoryRequiresProjectError() from exc
        if any(
            cls is not None and isinstance(exc, cls)
            for cls in (ForeignKeyViolation, InvalidTextRepresentation)
        ):
            raise CategoryNotAssignableError() from exc
        logger.exception("Failed to set analysis run category")
        raise AnalysisHistoryReadError("failed to update analysis history") from exc

    return True


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


class AnalysisJobCancelledConflictError(Exception):
    """Raised by create_queued_analysis_run() when the same
    (project_id, created_by_user_id, idempotency_key) belongs to a job
    that was cancelled (see cancel_queued_analysis_run() —
    fix/async-job-cancel-safety). Deliberately distinct from
    AnalysisJobCreateConflictError above: this is not about the input
    differing, it's that the key itself is no longer usable once its
    job was cancelled, *regardless* of whether the resubmitted input
    matches — resurrecting a cancelled job (returning it as if this
    call had just "idempotently" succeeded) would silently undo the
    cancellation, and creating a brand-new row for it would defeat the
    whole point of idempotency keys (the client must get a fresh key
    deliberately, by the same path it would for any other new
    operation, never by having a reused key "unstick" itself here).
    main.py turns this into a 409. Carries the existing (cancelled)
    job's id for diagnostics."""

    def __init__(self, existing_analysis_run_id: str):
        super().__init__("idempotency key belongs to a cancelled analysis job")
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
    official_url: str | None = None,
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
        # Task 6-D-5B (feature/official-info-candidate) — included so
        # a resubmission of the same idempotency key with a different
        # officialUrl is treated as a genuinely different request
        # (same "入力差分を意図せず無視しないこと" reasoning this
        # function's own docstring already states for every other
        # field here), and so officialUrl itself is recorded in the
        # stored input_snapshot for later replay/display.
        "officialUrl": official_url,
    }


def _fetch_existing_job_by_idempotency_key(
    cur, *, project_id: str, created_by_user_id: str, idempotency_key: str
):
    """Looks up an existing job by its exact idempotency key —
    deliberately matches a cancelled row too (no `deleted_at is null`
    filter): the caller must be able to tell "this key belongs to a
    cancelled job" apart from "this key doesn't exist yet", which is
    exactly what the returned `deleted_at` is for (see
    create_queued_analysis_run()'s and
    _resolve_job_after_unique_violation()'s use of it below)."""
    cur.execute(
        """
        select id, status, input_snapshot, deleted_at
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

    existing_id, existing_status, existing_snapshot, existing_deleted_at = existing
    if existing_deleted_at is not None:
        # The row that caused the violation was cancelled — never
        # resurrect it here either, same reasoning as the pre-insert
        # check in create_queued_analysis_run() above.
        raise AnalysisJobCancelledConflictError(str(existing_id))
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
    official_url: str | None = None,
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
    - it was cancelled (`deleted_at is not null`, see
      cancel_queued_analysis_run() below) -> always raises
      AnalysisJobCancelledConflictError (main.py -> 409), regardless of
      whether the input matches — checked *before* the input
      comparison below, since a cancelled job's key must never be
      treated as a normal idempotent replay (fix/async-job-cancel-safety:
      cancellation deliberately keeps `idempotency_key` set, precisely
      so this exact lookup keeps finding it and refusing to reuse it,
      rather than silently freeing the key for reuse).
    - not cancelled, same canonicalized input -> returns that job's
      existing id/status with created=False (no new row, no limit
      check — a retry of an already-accepted operation must never be
      rejected by the very limits meant to stop *new* operations).
    - not cancelled, different canonicalized input -> raises
      AnalysisJobCreateConflictError (main.py -> 409).

    Queued-job limits (docs/40 "8.3"): only checked when actually about
    to insert a new row (never on an idempotent replay, see above) —
    counts this *project's* and this *user's* currently-'queued' jobs
    (excluding any that have been cancelled via
    cancel_queued_analysis_run() below, i.e. `deleted_at is not null`
    — a cancelled job must free its slot, not count against the limit
    forever) and raises AnalysisJobLimitExceededError if either would
    meet or exceed its limit (main.py -> 429). Both counts are taken
    inside the same doubly-locked transaction, so neither check can be
    slipped past by a burst of concurrent requests — not a burst for
    the same project (the project lock), and not a burst from the same
    user spread across different projects (the user lock, which the
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
        official_url=official_url,
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
                    existing_id, existing_status, existing_snapshot, existing_deleted_at = existing
                    if existing_deleted_at is not None:
                        # This key belongs to a cancelled job — never
                        # create a new row for it, and never return
                        # the cancelled row as if this were a normal
                        # idempotent replay (that would silently
                        # resurrect it from the caller's point of
                        # view). See AnalysisJobCancelledConflictError's
                        # docstring for the full reasoning.
                        raise AnalysisJobCancelledConflictError(str(existing_id))
                    if existing_snapshot != canonical_input:
                        raise AnalysisJobCreateConflictError(str(existing_id))
                    return AnalysisJobCreateResult(
                        analysis_run_id=str(existing_id),
                        status=existing_status,
                        created=False,
                    )

                cur.execute(
                    "select count(*) from analysis_runs"
                    " where project_id = %s and status = 'queued' and deleted_at is null",
                    (project_id,),
                )
                if cur.fetchone()[0] >= max_queued_per_project:
                    raise AnalysisJobLimitExceededError(
                        "project", max_queued_per_project
                    )

                cur.execute(
                    "select count(*) from analysis_runs"
                    " where created_by_user_id = %s and status = 'queued' and deleted_at is null",
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
    except (
        AnalysisJobCreateConflictError,
        AnalysisJobCancelledConflictError,
        AnalysisJobLimitExceededError,
    ):
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


# --- Synchronous analysis idempotency (Task 6-B3,
# feature/sync-analyze-jwt-project-auth) ------------------------------
#
# Reuses the exact same `analysis_runs.idempotency_key`/
# `created_by_user_id` columns and unique index as the async job system
# above (migration 005) — no new migration needed. The two systems are
# kept from ever interfering with each other by a single structural
# fact: `create_running_analysis_run()` below inserts its row directly
# with status='running' (never 'queued'), so it can never be matched
# by claim_next_queued_analysis_run()'s `where status = 'queued'`
# query (migration 006) — a synchronous analysis run is never, even
# momentarily, visible to the async worker as something to claim.
# `complete_analysis_job()` (Phase 2, below) is reused unchanged to
# finalize a sync run, since its own WHERE clause
# (`id = %s and locked_by = %s and status = 'running' and
# lease_expires_at > now()`) already expresses exactly the ownership
# check a synchronous caller also needs — the caller here plays the
# role of its own single-shot "worker", using a freshly generated
# `locked_by` token purely to satisfy that WHERE clause, never
# registered anywhere else.
#
# Deliberately scoped to the *authenticated* path only
# (ANALYZE_AUTH_REQUIRED=true) — not usable for the anonymous path.
# The existing unique index's scope, `(project_id, created_by_user_id,
# idempotency_key) where idempotency_key is not null`, cannot enforce
# anything when `created_by_user_id` is NULL (every anonymous request):
# SQL NULL is never equal to NULL, so two anonymous callers reusing the
# same key would never collide in this index at all — there is no safe
# way to extend this same mechanism to anonymous callers without
# either inventing a new, unauthenticated-identity scheme (out of this
# task's scope) or scoping purely by `(project_id, idempotency_key)`,
# which would let two *different* anonymous visitors collide on the
# same client-generated key and see each other's result — exactly the
# "別ユーザー・別projectのrequestIdが衝突しても情報を漏らさない"
# requirement this task asks to uphold. The anonymous path is therefore
# left completely untouched by this section.
#
# --- Task 6-B4 usage-quota counters (migration 009) ------------------
#
# create_running_analysis_run() below now also accepts
# `required_counters: list[UsageCounterRequirement]` (empty/omitted by
# default) — when non-empty, every counter in the list is atomically
# reserved (insert-or-increment, rejecting if that specific counter is
# already at its limit) in the exact same transaction as the new
# analysis_runs/analysis_results row, before that transaction ever
# commits. If ANY counter is already at its limit, the whole
# transaction is abandoned (never committed — see
# _reserve_usage_counters()'s own docstring) and
# AnalysisQuotaExceededError is raised: no analysis_runs row, no
# analysis_results row, and no partially-incremented counter ever
# persists. main.py builds this list only when
# AnalyzeQuotaSettings.enforcement_enabled is true (see
# services/analyze_quota_settings.py) — an empty list here always
# means "no quota checked at all", which is also exactly what happens
# today when enforcement is disabled or (structurally) for the
# anonymous path, which never calls this function at all.
#
# A resubmission of an *existing* idempotency_key never reaches this
# counter-reservation step — _resolve_existing_sync_run() above always
# returns/raises before create_running_analysis_run() gets to the
# "genuinely new key" INSERT branch where required_counters is
# consulted. This is what guarantees "同じrequestIdの再送ではカウンター
# を増やさない" without any special-case code: the ordering already in
# place from Task 6-B3 does this for free.
#
# Deadlock avoidance: the two advisory locks create_running_analysis_run()
# already acquires (keyed by this request's project_id, then its
# created_by_user_id — see that function's own docstring) already
# serialize every counter this feature can ever touch, since every
# counter's scope_id is always either that exact project_id or that
# exact user_id. Two concurrent create_running_analysis_run() calls
# that could possibly contend over the same counter row are therefore
# already fully serialized before either one reaches the counter
# upserts at all — no new advisory lock key is needed. _reserve_usage_counters()
# still processes its list in a fixed, deterministic order (sorted by
# (scope_type, scope_id, metric, period_type)) purely as defense in
# depth against a future caller that might one day touch this table
# without holding those same two locks (e.g. a hypothetical future
# extension to the async job system) — not needed for this feature's
# own correctness today.


def daily_period_start(now: datetime | None = None) -> datetime:
    """UTC start-of-day for `now` (default: the current instant) —
    computed in application code, not SQL, so the result never depends
    on a connection's session TimeZone setting (see this section's
    module-level comment for why that matters for a value used as part
    of an exact-match upsert key)."""
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return instant.replace(hour=0, minute=0, second=0, microsecond=0)


def monthly_period_start(now: datetime | None = None) -> datetime:
    """UTC start-of-month for `now` — see daily_period_start()'s
    docstring for why this is computed in Python, not SQL."""
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return instant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class UsageCounterRequirement:
    """One usage-quota counter create_running_analysis_run() must
    atomically reserve (insert-or-increment, subject to `limit`)
    before a new synchronous analysis run is allowed to proceed.

    `scope_type` is "user" or "project"; `scope_id` is that user's or
    project's id. `metric` is "all_analyses" (every analysis, mock/off
    included) or a specific paid-provider metric ("dataforseo_sandbox"
    / "dataforseo_live" / "openai" / "anthropic" / "google" — see
    backend/main.py for how the resolved provider mode maps to one of
    these). `period_type` is "daily" or "monthly"; `period_start` must
    be daily_period_start()/monthly_period_start()'s own output for
    the current instant — this module never recomputes it. `limit` of
    0 means "never allow a single call" (a fully valid, meaningful
    value — see services/analyze_quota_settings.py)."""

    scope_type: Literal["user", "project"]
    scope_id: str
    metric: str
    period_type: Literal["daily", "monthly"]
    period_start: datetime
    limit: int


class AnalysisQuotaExceededError(Exception):
    """Raised by create_running_analysis_run() when any one
    UsageCounterRequirement in `required_counters` is already at its
    limit. main.py turns this into HTTP 429
    (analysis_quota_exceeded) — identifies exactly which counter was
    hit and when it next resets (`next_period_start`, computed by
    the caller as this counter's period_start plus one day/month)."""

    def __init__(
        self,
        *,
        scope_type: str,
        scope_id: str,
        metric: str,
        period_type: str,
        period_start: datetime,
        limit: int,
    ):
        super().__init__(
            f"usage quota exceeded: scope_type={scope_type!r} scope_id={scope_id!r} "
            f"metric={metric!r} period_type={period_type!r} limit={limit!r}"
        )
        self.scope_type = scope_type
        self.scope_id = scope_id
        self.metric = metric
        self.period_type = period_type
        self.period_start = period_start
        self.limit = limit


def _reserve_usage_counters(cur, required_counters: list[UsageCounterRequirement]) -> None:
    """Atomically reserves (insert-or-increment) every counter in
    `required_counters`, raising AnalysisQuotaExceededError on the
    first one already at its limit — called from inside
    create_running_analysis_run()'s own transaction, strictly before
    that transaction's conn.commit(), so a raise here (which this
    function never catches) propagates straight out through the
    caller's `with psycopg.connect(...) as conn:` block and triggers
    psycopg3's automatic ROLLBACK — undoing this call's own prior
    counter increments *and* the analysis_runs/analysis_results INSERT
    that happened earlier in the same transaction. No new row, no
    partially-incremented counter, ever persists on a 429. See this
    section's module-level comment for why a fixed processing order
    and no new advisory lock are both safe here.
    """
    for requirement in sorted(
        required_counters,
        key=lambda r: (r.scope_type, r.scope_id, r.metric, r.period_type),
    ):
        # `select ... where %s > 0` (rather than a plain `values (...)`)
        # on the INSERT side is deliberate, not cosmetic: a plain
        # `values (1)` INSERT always succeeds on the very first-ever
        # row for a given counter key regardless of `limit`, since the
        # `where count < limit` guard below only ever applies to the
        # ON CONFLICT DO UPDATE branch — never to the initial INSERT
        # itself. That would let limit=0 ("never allow a single call")
        # wrongly succeed exactly once, the first time this exact
        # counter key is ever touched. Guarding the SELECT with
        # `limit > 0` makes the INSERT itself produce zero candidate
        # rows whenever the limit is 0, so ON CONFLICT never even has
        # a row to consider and this correctly returns no row either
        # way — verified directly against real PostgreSQL 17 (see
        # Task 6-B4's completion report).
        cur.execute(
            """
            insert into analysis_usage_counters
                (scope_type, scope_id, metric, period_type, period_start, count)
            select %s, %s, %s, %s, %s, 1
            where %s > 0
            on conflict (scope_type, scope_id, metric, period_type, period_start)
            do update set count = analysis_usage_counters.count + 1, updated_at = now()
            where analysis_usage_counters.count < %s
            returning count
            """,
            (
                requirement.scope_type,
                requirement.scope_id,
                requirement.metric,
                requirement.period_type,
                requirement.period_start,
                requirement.limit,
                requirement.limit,
            ),
        )
        if cur.fetchone() is None:
            raise AnalysisQuotaExceededError(
                scope_type=requirement.scope_type,
                scope_id=requirement.scope_id,
                metric=requirement.metric,
                period_type=requirement.period_type,
                period_start=requirement.period_start,
                limit=requirement.limit,
            )


class SyncAnalysisStillRunningError(Exception):
    """Raised by create_running_analysis_run() when the same
    (project_id, created_by_user_id, idempotency_key) already has a
    run that is still genuinely 'running' (its lease has not expired)
    — main.py turns this into 409. The caller must not start a second
    analysis for the same key while the first is still in flight."""

    def __init__(self, existing_analysis_run_id: str):
        super().__init__("a synchronous analysis for this idempotency key is still running")
        self.existing_analysis_run_id = existing_analysis_run_id


class SyncAnalysisPreviouslyFailedError(Exception):
    """Raised by create_running_analysis_run() when the same
    (project_id, created_by_user_id, idempotency_key) belongs to a run
    that already reached 'failed' (either from a genuine pipeline
    failure, or because its lease expired — see the inline lazy-expiry
    check below). main.py turns this into 409. Deliberately never
    auto-retried: this backend cannot know whether an external paid
    API call already happened before the failure, the same reasoning
    fail_expired_running_analysis_runs() already documents for the
    async worker. The caller must start a genuinely new analysis (a
    fresh idempotency_key), never resubmit this same one."""

    def __init__(self, existing_analysis_run_id: str):
        super().__init__("a synchronous analysis for this idempotency key already failed")
        self.existing_analysis_run_id = existing_analysis_run_id


@dataclass(frozen=True)
class SyncAnalysisRunReservation:
    """Returned by create_running_analysis_run() on success.

    `created=True`: a brand-new row was inserted directly as 'running'
    — `locked_by` is the token the caller must pass to
    complete_analysis_job() (as `worker_id`) once the pipeline
    finishes; `result_json`/`meta_json` are both None.

    `created=False`: the same idempotency key already has a
    'completed'/'partial' run — `locked_by` is None (nothing to
    complete, there is no in-flight execution this call owns),
    `result_json`/`meta_json` are the already-saved result to replay
    as-is, and `analysis_run_id`/`status` identify and describe it.
    """

    analysis_run_id: str
    created: bool
    status: str
    locked_by: str | None
    result_json: dict[str, Any] | None = None
    meta_json: dict[str, Any] | None = None


def _replay_result_for_existing_sync_run(cur, existing_id) -> tuple[dict | None, dict | None]:
    cur.execute(
        "select result_json, meta_json from analysis_results where analysis_run_id = %s",
        (existing_id,),
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row is not None else (None, None)


def _resolve_existing_sync_run(conn, cur, existing, canonical_input: dict[str, Any]):
    """Shared by create_running_analysis_run()'s pre-insert lookup and
    its UniqueViolation defense-in-depth path below — given a non-None
    _fetch_existing_job_by_idempotency_key() result, either returns a
    SyncAnalysisRunReservation(created=False, ...) for a replayable
    terminal state, or raises for every other case. Must be called
    from inside the same transaction as the caller's advisory locks (or
    the UniqueViolation path's own fresh connection) so the lazy
    lease-expiry UPDATE below is consistent with whatever else that
    transaction does.

    Takes `conn` (not just `cur`) because the lazy lease-expiry UPDATE
    below must be committed *before* SyncAnalysisPreviouslyFailedError
    is raised out of this function — found by this task's real-
    PostgreSQL integration test, not by any mocked test: psycopg3's
    connection context manager rolls back on an exception propagating
    through its `with` block, so without this explicit commit, the
    very UPDATE that transitions the row to 'failed' would be silently
    undone the moment this function raises, leaving the row forever
    stuck as 'running' instead.
    """
    existing_id, existing_status, existing_snapshot, existing_deleted_at = existing
    if existing_deleted_at is not None:
        # Mirrors create_queued_analysis_run()'s own reasoning exactly
        # — a soft-deleted row's key must never be resurrected or
        # reused, regardless of input.
        raise AnalysisJobCancelledConflictError(str(existing_id))
    if existing_snapshot != canonical_input:
        raise AnalysisJobCreateConflictError(str(existing_id))

    if existing_status == "running":
        # Lazily expires a dead lease right here, rather than waiting
        # for fail_expired_running_analysis_runs()'s own background
        # sweep (which, with ANALYSIS_JOBS_WORKER_ENABLED=false in
        # production today, never runs at all) — see this section's
        # module-level comment and docs/40 "11.4"'s "never auto-retry
        # after a lease expires" rule, which applies here identically.
        # Scoped to this exact row and re-checks `status = 'running'`
        # in the WHERE clause so a concurrent caller that already
        # expired/completed it a moment ago simply updates zero rows
        # here instead of double-writing.
        cur.execute(
            """
            update analysis_runs
            set status = 'failed',
                completed_at = now(),
                error_message = 'worker lease expired (possible partial execution, not auto-retried)'
            where id = %s
              and status = 'running'
              and lease_expires_at < now()
            returning id
            """,
            (existing_id,),
        )
        if cur.fetchone() is not None:
            existing_status = "failed"
            # Must be committed now — see this function's docstring.
            conn.commit()
        else:
            raise SyncAnalysisStillRunningError(str(existing_id))

    if existing_status == "failed":
        raise SyncAnalysisPreviouslyFailedError(str(existing_id))

    # completed / partial -> replay the already-saved result as-is.
    result_json, meta_json = _replay_result_for_existing_sync_run(cur, existing_id)
    return SyncAnalysisRunReservation(
        analysis_run_id=str(existing_id),
        created=False,
        status=existing_status,
        locked_by=None,
        result_json=result_json,
        meta_json=meta_json,
    )


def _resolve_sync_run_after_unique_violation(
    database_url: str,
    *,
    project_id: str,
    created_by_user_id: str,
    idempotency_key: str,
    canonical_input: dict[str, Any],
):
    """Defense-in-depth path for create_running_analysis_run() — see
    its docstring and _resolve_job_after_unique_violation()'s own
    analogous comment above. The transaction that hit the
    UniqueViolation is already aborted, so this re-queries on a
    brand-new connection and transaction."""
    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                existing = _fetch_existing_job_by_idempotency_key(
                    cur,
                    project_id=project_id,
                    created_by_user_id=created_by_user_id,
                    idempotency_key=idempotency_key,
                )
                if existing is None:
                    raise AnalysisHistoryReadError("failed to create synchronous analysis run")
                result = _resolve_existing_sync_run(conn, cur, existing, canonical_input)
            conn.commit()
    except (
        AnalysisJobCancelledConflictError,
        AnalysisJobCreateConflictError,
        SyncAnalysisStillRunningError,
        SyncAnalysisPreviouslyFailedError,
    ):
        raise
    except Exception as exc:
        logger.exception("Failed to resolve synchronous analysis run after unique constraint conflict")
        raise AnalysisHistoryReadError("failed to create synchronous analysis run") from exc

    return result


def create_running_analysis_run(
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
    lease_seconds: int,
    required_counters: list[UsageCounterRequirement] | None = None,
    official_url: str | None = None,
) -> SyncAnalysisRunReservation:
    """Atomically reserves one synchronous, authenticated POST /analyze
    request's execution slot — Task 6-B3's idempotency mechanism. See
    this section's module-level comment for why this is safe to share
    the async job system's schema/columns without ever letting
    claim_next_queued_analysis_run() see (let alone claim) the row this
    creates.

    Locking/idempotency-lookup structure mirrors
    create_queued_analysis_run() exactly (same two fixed-order
    advisory locks, same _fetch_existing_job_by_idempotency_key()
    lookup, same UniqueViolation defense-in-depth fallback) — see that
    function's docstring for the full reasoning, not repeated here.
    The one structural difference: on a genuinely new key, this
    function inserts the new row directly with status='running' (plus
    locked_by/locked_at/lease_expires_at already set), never 'queued' —
    there is no separate "wait for a worker to claim it" phase, because
    the caller (main.py's analyze()) *is* the thing that executes it,
    synchronously, in this same request.

    `required_counters` (Task 6-B4, default empty — no quota checked
    at all) is only ever consulted on the "genuinely new key" branch
    below, strictly before this transaction's own conn.commit() — see
    _reserve_usage_counters()'s and this section's own module-level
    comment for why a resubmission of an existing key never touches it,
    why no new advisory lock is needed, and why a rejection here undoes
    the row INSERT too.

    Raises SyncAnalysisStillRunningError / SyncAnalysisPreviouslyFailedError
    / AnalysisJobCreateConflictError / AnalysisJobCancelledConflictError
    / AnalysisQuotaExceededError for every non-replayable existing-row
    or over-limit case (see their own docstrings) — main.py maps the
    first four to 409 and the last to 429. Raises
    AnalysisHistoryReadError on any other connection/query failure
    (including any failure while reserving `required_counters` itself
    — never silently treated as "quota check skipped, proceed anyway").
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
        official_url=official_url,
    )
    locked_by = f"sync:{uuid.uuid4()}"

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # Same fixed (project, then user) lock order as
                # create_queued_analysis_run() — see that function's
                # docstring for why this ordering rules out a deadlock
                # between two transactions.
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
                    result = _resolve_existing_sync_run(conn, cur, existing, canonical_input)
                    conn.commit()
                    return result

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
                         created_by_user_id, idempotency_key,
                         locked_by, locked_at, lease_expires_at, attempt_count)
                    values (%s, %s, 'running', %s, %s, %s,
                            %s, now(), now() + make_interval(secs => %s), 1)
                    returning id
                    """,
                    (
                        brand_id,
                        project_id,
                        Jsonb(canonical_input),
                        created_by_user_id,
                        idempotency_key,
                        locked_by,
                        lease_seconds,
                    ),
                )
                analysis_run_id = cur.fetchone()[0]

                cur.execute(
                    "insert into analysis_results (analysis_run_id, result_json) values (%s, %s)",
                    (analysis_run_id, Jsonb({})),
                )

                # Task 6-B4: must happen before conn.commit() below —
                # a raise here (never caught in this function) rolls
                # back the two INSERTs above too, via psycopg3's
                # automatic ROLLBACK-on-exception (see
                # _reserve_usage_counters()'s docstring).
                _reserve_usage_counters(cur, required_counters or [])
            conn.commit()
    except (
        AnalysisJobCreateConflictError,
        AnalysisJobCancelledConflictError,
        SyncAnalysisStillRunningError,
        SyncAnalysisPreviouslyFailedError,
        AnalysisQuotaExceededError,
    ):
        raise
    except Exception as exc:
        if UniqueViolation is not None and isinstance(exc, UniqueViolation):
            return _resolve_sync_run_after_unique_violation(
                database_url,
                project_id=project_id,
                created_by_user_id=created_by_user_id,
                idempotency_key=idempotency_key,
                canonical_input=canonical_input,
            )
        logger.exception("Failed to create synchronous analysis run")
        raise AnalysisHistoryReadError("failed to create synchronous analysis run") from exc

    return SyncAnalysisRunReservation(
        analysis_run_id=str(analysis_run_id),
        created=True,
        status="running",
        locked_by=locked_by,
    )


# --- Async analysis jobs, Phase 2 worker (services/analysis_job_worker.py)
# — see docs/40_async_analysis_jobs_design.md "11"/"12". Three new
# functions: claim_next_queued_analysis_run() (queued -> running,
# exclusive), complete_analysis_job() (running -> completed/partial/
# failed, exclusive, atomic with the result write — also reused as-is
# by create_running_analysis_run() above for Task 6-B3's synchronous
# idempotency, with the synchronous caller itself playing the role of
# a single-shot "worker"), and fail_expired_running_analysis_runs()
# (the lease-expiry sweep, used only by the worker's own poll loop —
# create_running_analysis_run() above does its own narrower, inline,
# single-row equivalent instead, so it keeps working correctly even
# when ANALYSIS_JOBS_WORKER_ENABLED=false). None of these three are
# called by anything in Phase 1 — they are reachable only via the
# worker, which is itself off unless ANALYSIS_JOBS_WORKER_ENABLED=true
# (services/analysis_jobs_settings.py).


@dataclass(frozen=True)
class ClaimedAnalysisJob:
    """Returned by claim_next_queued_analysis_run() when a job was
    actually claimed. `input_snapshot` is exactly what
    create_queued_analysis_run() stored at job-creation time (docs/40
    "5"/"6.1") — the worker rebuilds its call to
    main.run_analysis_pipeline() entirely from this dict, never from
    anything else.

    `project_id`/`created_by_user_id` (Task 6-D-5C-2,
    feature/claude-fact-extraction-mvp) are the same `analysis_runs`
    columns create_queued_analysis_run() wrote at creation time —
    added so services/analysis_job_worker.py can call
    services/fact_extraction_provider.py's attempt_fact_extraction()
    (which needs a project_id/user_id to reserve quota against) for an
    async job the exact same way backend/main.py's authenticated sync
    path already does. Default to `None` so the many existing tests
    that construct `ClaimedAnalysisJob` without these two fields keep
    working unchanged.
    """

    analysis_run_id: str
    input_snapshot: dict[str, Any]
    attempt_count: int
    project_id: str | None = None
    created_by_user_id: str | None = None


def claim_next_queued_analysis_run(
    *, worker_id: str, lease_seconds: int
) -> ClaimedAnalysisJob | None:
    """Atomically claims the oldest 'queued' analysis_runs row for
    `worker_id`, transitioning it to 'running' — see
    docs/40_async_analysis_jobs_design.md "11.1". Returns None when
    there is no queued row to claim (not an error).

    Excludes soft-deleted rows (`deleted_at is not null`) — see
    cancel_queued_analysis_run() below, added alongside this fix. A
    caller who cancels a queued job before a worker claims it must
    have that cancellation actually honored; without this condition, a
    row soft-deleted while still 'queued' (already hidden from every
    history list/detail read path, which filters on `deleted_at is
    null`) would still be silently claimed and executed here, directly
    contradicting what the cancellation told the caller it did.

    Uses `for update skip locked` inside the id-selecting subquery so
    multiple worker processes/tasks polling concurrently (see docs/40
    "12.3": uvicorn with `--workers` > 1, or more than one Render
    instance) never block on each other and never claim the same row
    — each claim attempt either gets a distinct unlocked 'queued' row
    or finds none available and returns None, with no contention
    between concurrent callers beyond normal row-level locking.

    Sets `locked_by = worker_id`, `locked_at = now()`,
    `lease_expires_at = now() + lease_seconds`, and increments
    `attempt_count`. `started_at` (meaning "became queued", set at
    creation time by create_queued_analysis_run()) is deliberately
    left untouched — see docs/40 "13.5" for why `locked_at` is a
    separate column rather than redefining `started_at`.

    Raises AnalysisHistoryReadError on any connection/query failure
    (mirrors every other function in this module).
    """
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set status = 'running',
                        locked_by = %s,
                        locked_at = now(),
                        lease_expires_at = now() + make_interval(secs => %s),
                        attempt_count = attempt_count + 1
                    where id = (
                        select id
                        from analysis_runs
                        where status = 'queued'
                          and deleted_at is null
                        order by created_at asc
                        limit 1
                        for update skip locked
                    )
                    returning id, input_snapshot, attempt_count, project_id, created_by_user_id
                    """,
                    (worker_id, lease_seconds),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to claim next queued analysis job")
        raise AnalysisHistoryReadError("failed to claim analysis job") from exc

    if row is None:
        return None

    analysis_run_id, input_snapshot, attempt_count, project_id, created_by_user_id = row
    return ClaimedAnalysisJob(
        analysis_run_id=str(analysis_run_id),
        input_snapshot=input_snapshot,
        attempt_count=attempt_count,
        project_id=str(project_id) if project_id is not None else None,
        created_by_user_id=str(created_by_user_id) if created_by_user_id is not None else None,
    )


@dataclass(frozen=True)
class CancelQueuedAnalysisJobResult:
    """Returned by cancel_queued_analysis_run() — main.py's DELETE
    /analysis-jobs/{id} maps `outcome` to an HTTP status:

    - "cancelled": this call just cancelled the job (200).
    - "already_cancelled": the job was already cancelled by an earlier
      call — treated as a successful no-op, mirroring
      soft_delete_analysis_run()'s existing "repeat delete succeeds"
      convention (200).
    - "not_cancellable": the job exists and is not soft-deleted, but
      is no longer 'queued' (a worker already claimed it, or it
      already reached a terminal status) — never reported as success,
      since this function never stops a 'running' job or undoes a
      finished one (main.py -> 409). `status` carries the job's actual
      current status for the error message.
    - "not_found": `analysis_run_id` doesn't exist or is malformed
      (main.py -> 404).
    """

    outcome: Literal["cancelled", "already_cancelled", "not_cancellable", "not_found"]
    status: str | None = None


def cancel_queued_analysis_run(analysis_run_id: str) -> CancelQueuedAnalysisJobResult:
    """Cancels one job while it is still 'queued' — the only state a
    cancellation can actually prevent from ever running (docs/40
    "11.4"-equivalent reasoning extended to cancellation: once a
    worker has claimed a job, nothing in this process can safely stop
    it mid-flight — see services/analysis_job_worker.py's
    asyncio.to_thread() docstring — so this function deliberately
    never touches a 'running' row and never claims to have cancelled
    one).

    The single atomic `update ... where status = 'queued' and
    deleted_at is null` below is what makes this race-safe against
    claim_next_queued_analysis_run()'s own atomic claim (which now
    requires the same two conditions, see that function's docstring):
    whichever of the two UPDATEs commits first on a given row decides
    the outcome — PostgreSQL's row-level locking means the second one
    to reach that row re-evaluates its WHERE clause against the
    now-committed data and simply matches zero rows if it lost the
    race, never double-claims or double-cancels the same row. No
    explicit locking beyond each statement's own row lock is needed.

    Deliberately does **not** clear `idempotency_key` (an earlier
    version of this function did — see fix/async-job-cancel-safety's
    initial commit — but that let a resubmission with the same key
    silently create a brand-new job instead of being refused, which
    defeats the point of cancelling: the caller could get back a
    "new" job that looks like nothing happened). Keeping the key set
    means _fetch_existing_job_by_idempotency_key() keeps finding this
    row, and create_queued_analysis_run() checks `deleted_at` on that
    lookup specifically to refuse a replay against a cancelled job
    (AnalysisJobCancelledConflictError, main.py -> 409) rather than
    creating a new row or returning this one as if it were a normal
    idempotent success — see that function's docstring. A genuinely
    *new* "start analysis" operation (a fresh idempotency key, which
    is what a client generates for any explicit new attempt — see
    app/lib/analysis-jobs.ts's clearPendingJobSubmission()) is
    unaffected: a different key never matches this row at all.

    Raises AnalysisHistoryReadError on any connection/query failure.
    """
    try:
        uuid.UUID(analysis_run_id)
    except (ValueError, AttributeError, TypeError):
        return CancelQueuedAnalysisJobResult(outcome="not_found")

    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set deleted_at = now()
                    where id = %s
                      and status = 'queued'
                      and deleted_at is null
                    returning id
                    """,
                    (analysis_run_id,),
                )
                cancelled_now = cur.fetchone() is not None

                if cancelled_now:
                    conn.commit()
                    return CancelQueuedAnalysisJobResult(outcome="cancelled")

                # The UPDATE above matched nothing — distinguish why,
                # without having committed any write yet.
                cur.execute(
                    "select status, deleted_at from analysis_runs where id = %s",
                    (analysis_run_id,),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to cancel queued analysis job")
        raise AnalysisHistoryReadError("failed to cancel analysis job") from exc

    if row is None:
        return CancelQueuedAnalysisJobResult(outcome="not_found")

    status, deleted_at = row
    if deleted_at is not None:
        return CancelQueuedAnalysisJobResult(outcome="already_cancelled")
    return CancelQueuedAnalysisJobResult(outcome="not_cancellable", status=status)


def extend_analysis_job_lease(
    analysis_run_id: str, *, worker_id: str, lease_seconds: int
) -> bool:
    """Heartbeat: extends a claimed job's `lease_expires_at` while its
    owning worker is still actively running it — see
    docs/40_async_analysis_jobs_design.md "11.3"/"21" (heartbeat). A
    long-running job (e.g. every provider ON, ~100s worst case) must
    not be allowed to outlive its original lease and get reaped by
    fail_expired_running_analysis_runs() while the worker that claimed
    it is still genuinely working on it.

    Conditioned on `locked_by = worker_id and status = 'running' and
    lease_expires_at > now()` — the exact same three-part check
    complete_analysis_job() uses, for the exact same reason: this must
    never extend a lease that isn't this worker's, isn't 'running'
    anymore, or has *already* expired (even by a moment, even if the
    sweeper hasn't run yet) — a heartbeat is not a resurrection
    mechanism, see docs/40 "11.4"'s "no automatic revival of an
    expired lease" rule, which applies here just as much as it does to
    fail_expired_running_analysis_runs() itself.

    Returns True when the lease was extended, False when any of the
    three conditions failed — the caller (services/analysis_job_worker.py's
    heartbeat loop) must treat False as "I no longer own this job":
    stop heartbeating, and do not start any further work (including
    any further external API call this job's remaining pipeline
    execution might otherwise still make — see that module's
    docstring for the hard limit on how much control is actually
    possible here, since the pipeline call itself cannot be
    interrupted mid-flight).

    Raises AnalysisHistoryReadError on any connection/query failure —
    callers should treat a *raised* exception here differently from a
    *returned* False: a raised exception means "I don't know whether I
    still own the lease" (a transient DB problem), not "I definitely
    lost it".
    """
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set lease_expires_at = now() + make_interval(secs => %s)
                    where id = %s
                      and locked_by = %s
                      and status = 'running'
                      and lease_expires_at > now()
                    returning id
                    """,
                    (lease_seconds, analysis_run_id, worker_id),
                )
                extended = cur.fetchone() is not None
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to extend analysis job lease")
        raise AnalysisHistoryReadError("failed to extend analysis job lease") from exc

    return extended


def complete_analysis_job(
    analysis_run_id: str,
    *,
    worker_id: str,
    status: str,
    result_json: dict[str, Any] | None,
    meta_json: dict[str, Any] | None,
    error_message: str | None,
) -> bool:
    """Atomically finalizes a claimed job — backs
    services/analysis_job_worker.py's completion step. `status` must
    be 'completed', 'partial', or 'failed'.

    The `analysis_runs` status/completed_at/error_message update and
    the `analysis_results` result_json/meta_json update (when
    `result_json` is not None — a 'failed' job passes `result_json=
    None` and this function leaves the existing placeholder
    `result_json='{}'` untouched, since there is nothing real to
    write) happen in the **same transaction**, so a crash between the
    two can never leave one updated and not the other — see docs/40
    "11.6".

    The `analysis_runs` update is conditioned on
    `locked_by = worker_id and status = 'running' and lease_expires_at
    > now()` — see docs/40 "11.5". The third condition
    (`lease_expires_at > now()`) is deliberately checked here *in
    addition to* `status = 'running'`, not instead of it: a lease that
    has expired but hasn't been swept to 'failed' yet by
    fail_expired_running_analysis_runs() (the sweeper runs on its own
    schedule, not synchronously with every write) would otherwise
    still read as "status = running" and let a stale completion slip
    through the gap between the lease actually expiring and the
    sweeper noticing. Either condition failing — this worker no
    longer owns the row, or its lease has (even very recently) expired
    — means this UPDATE matches zero rows, and this function returns
    False **without writing anything** — including the
    `analysis_results` update, which only runs when the
    `analysis_runs` update actually matched a row. Callers (the
    worker) must treat a False return as "my result arrived too late
    to matter" and log a warning rather than retrying or raising — see
    services/analysis_job_worker.py.

    Raises AnalysisHistoryReadError on any connection/query failure.
    """
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set status = %s,
                        completed_at = now(),
                        error_message = %s
                    where id = %s
                      and locked_by = %s
                      and status = 'running'
                      and lease_expires_at > now()
                    returning id
                    """,
                    (status, error_message, analysis_run_id, worker_id),
                )
                updated = cur.fetchone() is not None

                if updated and result_json is not None:
                    cur.execute(
                        """
                        update analysis_results
                        set result_json = %s, meta_json = %s
                        where analysis_run_id = %s
                        """,
                        (Jsonb(result_json), _maybe_jsonb(meta_json), analysis_run_id),
                    )
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to complete analysis job")
        raise AnalysisHistoryReadError("failed to complete analysis job") from exc

    return updated


def fail_expired_running_analysis_runs() -> list[str]:
    """Sweeps every 'running' row whose `lease_expires_at` has already
    passed and transitions it directly to 'failed' — **never** back to
    'queued' (see docs/40_async_analysis_jobs_design.md "11.4": this
    backend cannot know whether an external paid API call already
    happened before the owning worker disappeared, so a lease expiry
    is always a terminal failure, never an automatic retry). Returns
    the ids of every row this call transitioned (for logging); an
    empty list means nothing was expired, not an error.

    Called at the start of every poll cycle by
    services/analysis_job_worker.py, before attempting to claim a new
    job — this is also what makes an abandoned job (a crashed worker,
    a Render restart/sleep mid-job) eventually resolve to 'failed' once
    *any* process's poll cycle runs again, even one that didn't own
    the lease.

    Raises AnalysisHistoryReadError on any connection/query failure.
    """
    database_url = _require_connectable()

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update analysis_runs
                    set status = 'failed',
                        completed_at = now(),
                        error_message = 'worker lease expired (possible partial execution, not auto-retried)'
                    where status = 'running'
                      and lease_expires_at < now()
                    returning id
                    """
                )
                expired_ids = [str(row[0]) for row in cur.fetchall()]
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to sweep expired analysis job leases")
        raise AnalysisHistoryReadError("failed to sweep expired analysis jobs") from exc

    return expired_ids
