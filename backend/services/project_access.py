"""Project-level access control helpers — groundwork for backend JWT
authorization (see docs/32_backend_jwt_verification_design.md "9.
project権限判定").

None of these functions are called by any API endpoint yet. The
existing GET /analysis-runs / GET /analysis-runs/{id} / GET
/analysis-runs/{id}/comparison endpoints remain gated solely by
HISTORY_READ_TOKEN (see main.py's _check_history_read_access()) — a
verified JWT (services/jwt_auth.py) alone must never be treated as
authorization to read another user's history, since these helpers
aren't wired into anything that decides what a request may see yet.

Every function here takes an already-open DB connection (`conn`)
rather than opening its own, so a future caller can reuse one
connection across an authorization check and the data query that
follows it — one level up from get_default_project_id()'s
cursor-taking style in services/analysis_history_repository.py.

`conn` is duck-typed (only `.cursor()` is used) rather than imported as
a `psycopg.Connection` type, so this module has no import-time
dependency on the psycopg driver at all.

None of user_id/project_id/analysis_run_id are secrets, but this
module never receives or handles a raw token/JWT — only an
already-verified user_id — so there is nothing token-shaped to
accidentally log here.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ProjectAccessError(Exception):
    """Raised on a connection/query failure while checking project
    access — distinct from a normal "no access" result (False/[]),
    which is not an error condition. Mirrors
    services.analysis_history_repository.AnalysisHistoryReadError:
    once these helpers are wired into an API endpoint, a caller should
    treat this the same way (e.g. respond 503)."""


def can_user_access_project(conn: Any, user_id: str, project_id: str) -> bool:
    """True only if `user_id` is a member of the organization that owns
    `project_id`. Returns False (never raises) for an empty
    user_id/project_id — neither can ever match a real row, and this
    also guards against a caller accidentally passing an empty string
    as an unintended wildcard.

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id or not project_id:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from organization_members om
                join projects p on p.organization_id = om.organization_id
                where om.user_id = %s
                  and p.id = %s
                limit 1
                """,
                (user_id, project_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to check project access")
        raise ProjectAccessError("failed to check project access") from exc

    return row is not None


def can_user_access_analysis_run(conn: Any, user_id: str, analysis_run_id: str) -> bool:
    """True only if `user_id` is a member of the organization that owns
    the project `analysis_run_id` belongs to. Returns False (never
    raises) for an empty user_id/analysis_run_id, a nonexistent
    analysis_run_id, or an analysis_run whose `project_id` is null —
    the inner join from analysis_runs.project_id to projects.id
    naturally excludes a null project_id, since there is no project to
    check membership against.

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id or not analysis_run_id:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from analysis_runs ar
                join projects p on p.id = ar.project_id
                join organization_members om on om.organization_id = p.organization_id
                where ar.id = %s
                  and om.user_id = %s
                limit 1
                """,
                (analysis_run_id, user_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to check analysis run access")
        raise ProjectAccessError("failed to check analysis run access") from exc

    return row is not None


def can_user_cancel_analysis_run(conn: Any, user_id: str, analysis_run_id: str) -> bool:
    """True only if `user_id` is the user who *created* this job
    (`analysis_runs.created_by_user_id`) — deliberately stricter than
    can_user_access_analysis_run() above (project membership), which
    would let any other member of the same project cancel someone
    else's queued job. main.py's DELETE /analysis-jobs/{id}
    (fix/async-job-cancel-safety) uses this instead of the
    project-membership check every other /analysis-jobs* endpoint
    uses — cancellation is scoped to "undo your own not-yet-started
    request", not a project-wide operation; adding a project-admin
    override is explicitly out of scope for now.

    Returns False (never raises) for an empty user_id/analysis_run_id,
    a nonexistent analysis_run_id, or a row with a null
    created_by_user_id (every row saved by the existing synchronous
    POST /analyze, which has no caller identity at all) — same
    existence-leak avoidance as can_user_access_analysis_run() (a
    caller who isn't the creator gets the same 403 whether the run
    belongs to someone else or doesn't exist at all).

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id or not analysis_run_id:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from analysis_runs where id = %s and created_by_user_id = %s limit 1",
                (analysis_run_id, user_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to check analysis run cancel ownership")
        raise ProjectAccessError("failed to check analysis run cancel ownership") from exc

    return row is not None


def can_user_access_tag(conn: Any, user_id: str, tag_id: str) -> bool:
    """True only if `user_id` is a member of the organization that owns
    the project `tag_id` belongs to — mirrors
    can_user_access_analysis_run() above exactly, one table swapped
    (feature/history-tags-categories). Returns False (never raises)
    for an empty user_id/tag_id, a nonexistent tag_id, or a malformed
    (non-UUID) tag_id — a bad UUID literal makes the `=` comparison
    below simply match no row rather than raising, so no separate
    `uuid.UUID(...)` pre-check is needed here.

    Deliberately gives the same False/403 outcome whether `tag_id`
    doesn't exist at all or exists in a project `user_id` can't
    access — same existence-leak avoidance as
    can_user_access_analysis_run().

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id or not tag_id:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from tags t
                join projects p on p.id = t.project_id
                join organization_members om on om.organization_id = p.organization_id
                where t.id = %s
                  and om.user_id = %s
                limit 1
                """,
                (tag_id, user_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to check tag access")
        raise ProjectAccessError("failed to check tag access") from exc

    return row is not None


def can_user_access_category(conn: Any, user_id: str, category_id: str) -> bool:
    """True only if `user_id` is a member of the organization that owns
    the project `category_id` belongs to — mirrors
    can_user_access_tag() above exactly, one table swapped
    (feature/history-tags-categories).

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id or not category_id:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from categories c
                join projects p on p.id = c.project_id
                join organization_members om on om.organization_id = p.organization_id
                where c.id = %s
                  and om.user_id = %s
                limit 1
                """,
                (category_id, user_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.exception("Failed to check category access")
        raise ProjectAccessError("failed to check category access") from exc

    return row is not None


def get_accessible_project_ids(conn: Any, user_id: str) -> list[str]:
    """Returns the id of every project `user_id` can access (every
    project belonging to an organization `user_id` is a member of),
    ordered by project creation time then id for a stable, deterministic
    order. Returns [] (never raises for this case) for an empty
    user_id or a user with no memberships.

    Deduplicates defensively — the schema's uniqueness constraints
    (organization_members' (organization_id, user_id) primary key,
    projects.organization_id being non-null) already prevent a project
    from appearing twice for the same user, but this keeps the
    contract explicit regardless of schema details.

    Raises ProjectAccessError on a connection/query failure.
    """
    if not user_id:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select p.id
                from projects p
                join organization_members om on om.organization_id = p.organization_id
                where om.user_id = %s
                order by p.created_at asc, p.id asc
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.exception("Failed to list accessible projects")
        raise ProjectAccessError("failed to list accessible projects") from exc

    return list(dict.fromkeys(str(row[0]) for row in rows))
