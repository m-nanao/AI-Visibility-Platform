"""Task 6-D-2B (feature/websearch-quota-reservation): atomically
reserves daily/monthly quota for a *future* conditional Web-search
follow-up call, against an *already-existing* analysis run.

**This is a separate function from
services.analysis_history_repository.create_running_analysis_run().**
That function exists to atomically create a brand-new 'running'
analysis_runs row for a new synchronous /analyze request (Task 6-B3's
idempotency mechanism) — reusing it here would be wrong on every
level: there is no new run to create (the run this reservation is
*for* already exists and is already 'running'), no new idempotency
key, and no new brand/analysis_results row. This module only ever
reads the existing analysis_runs row (to validate it) and
inserts/increments rows in the existing analysis_usage_counters table
(Task 6-B4) — it never touches analysis_runs/analysis_results/brands.

**Scope of this task**: only the quota-reservation primitive itself.
No Web search API is called or implemented anywhere in this module or
by anything that calls it. Nothing in the existing /analyze request
path (backend/main.py's _resolve_required_usage_counters()/
_analyze_authenticated_idempotent()) calls this function yet — wiring
it into an actual conditional-search feature is explicitly a future
task's job.

Validates three things before ever touching analysis_usage_counters,
exactly in the order "is this even a legal request" ->
"is the caller allowed to make it" -> "does quota allow it":

1. `metric` must be one of WEBSEARCH_METRICS — the three Task 6-D-2A
   metrics (openai_websearch/anthropic_websearch/google_websearch) plus
   Task 6-D-4C-2's gemini_external_document. This is a
   *programming-error* guard, not a user-input validation:
   nothing in this codebase lets an HTTP request body choose this
   value freely (no endpoint calls this function at all yet), but a
   future caller must not be able to pass an arbitrary string through
   to analysis_usage_counters — restricting it here, in one place,
   means that guarantee holds regardless of what the future caller
   looks like.
2. The given `analysis_run_id` must exist, belong to `project_id`
   (not just *some* project — exactly the one the caller claims), be
   currently 'running' (not already completed/failed/queued — a
   websearch follow-up only ever makes sense while the original
   synchronous request that owns this run is still in flight), and
   not soft-deleted.
3. `user_id` must be able to access `project_id` (reuses
   services.project_access.can_user_access_analysis_run() — the same,
   already-tested project-membership check every other authenticated
   endpoint in this codebase uses).

Only once all three hold does this reserve the daily *and* monthly
websearch counters for `metric`, atomically, in the same database
transaction — reusing
services.analysis_history_repository._reserve_usage_counters()'s
exact, already-proven (real-PostgreSQL-tested) atomic
insert-or-increment-with-cap primitive rather than duplicating its
SQL. Both counters are checked together: if either is already at its
limit (0 by default — see services/analyze_quota_settings.py), the
whole transaction raises AnalysisQuotaExceededError and rolls back —
no partial increment of just the daily or just the monthly counter
ever persists (same guarantee create_running_analysis_run() already
relies on for its own provider counters).

**Same-run/same-provider double reservation (Task 6-D-2B item "3",
then its follow-up "additional implementation" task)**: originally
left unimplemented (see git history / the first completion report for
the full investigation into why no existing table/column could safely
hold this marker). Now solved by migrations/010_add_analysis_run_websearch_reservations.sql's
new `analysis_run_websearch_reservations` table — a dedicated,
narrowly-scoped `primary key (analysis_run_id, metric)` that exists
for exactly one purpose ("has this run already reserved this
provider's websearch quota") and is never read by any existing API
endpoint, so it carries none of the transient-exposure risk a reused
`analysis_results.meta_json` scratch flag would have had.

The reservation-marker insert and the daily/monthly counter increments
now happen in the same database transaction, in this order:

1. `insert into analysis_run_websearch_reservations ... on conflict
   (analysis_run_id, metric) do nothing returning analysis_run_id` —
   atomically checks-and-sets the marker. If this returns no row (the
   marker already existed), WebsearchQuotaAlreadyReservedError is
   raised immediately and the transaction is abandoned *before ever
   touching analysis_usage_counters* — a second reservation attempt
   for the same (analysis_run_id, metric) never increments the
   counters a second time (Task 6-D-2B follow-up item "6").
2. Only if the marker insert actually inserted a new row does this
   proceed to _reserve_usage_counters() exactly as before. If that
   then raises AnalysisQuotaExceededError (limit reached), the whole
   transaction rolls back — undoing the marker insert from step 1 too,
   so a rejected reservation leaves no trace in either table (item
   "9").

Only a successful run of both steps is committed, so the marker and
the two counter increments are always all three present together or
none of them are — there is no state where the marker exists but the
counters weren't incremented, or vice versa.

**This still does not, and cannot, prevent a caller from calling the
real (future) Web-search API itself more than once "for free" using
one successful reservation** — see WebsearchQuotaAlreadyReservedError's
own docstring and this task's completion report item "12": reserving
quota and actually calling an external API are two separate steps a
future caller must still keep one-to-one in its own logic. This module
only guarantees the *quota bookkeeping* side of that is never double
counted.

**Task 6-D-5C-4G (feature/async-analysis-supplements) — optional async
lease validation, added in the same transaction as everything above**:
backend/services/analysis_job_worker.py's background job worker (Task
6-D-5C-4C) shares this exact function with the synchronous
authenticated /analyze path, but a worker's ownership of its job can
silently lapse (its lease can expire) while this function's own
original validation only ever checked `analysis_runs.status ==
'running'` — never `lease_expires_at`/`locked_by` — so a worker whose
lease had already lapsed could still have this function reserve quota
and go on to make one real, paid API call whose result would
ultimately be discarded (see docs/claude-task-handoff.md's Task
6-D-5C-4D/4E/4F entries for the full incident history and the earlier,
weaker, worker-side-only mitigation Task 6-D-5C-4E added —
_reverify_lease_before_next_step() in analysis_job_worker.py, which
this task's fix supplements rather than replaces: both now exist,
closing the gap from two independent directions).

`async_worker_id: str | None = None` is the new, fully optional,
backward-compatible parameter this task adds. The **default (`None`)
preserves today's exact behavior, byte for byte** — every synchronous
caller (backend/main.py's _analyze_authenticated_idempotent()) omits
it and is completely unaffected by this change. Passed non-None (by
the async worker's own call chain only — see
services/analysis_supplement_orchestrator.py and
services/fact_extraction_provider.py, both of which thread an
`async_worker_id` parameter through from
services/analysis_job_worker.py's `worker_id`), this function
additionally requires, **inside the exact same transaction and under
the exact same project-scoped advisory lock already described
above**, that:

- `analysis_runs.locked_by` equals `async_worker_id` exactly, and
- `analysis_runs.lease_expires_at` is non-null and strictly greater
  than the database server's own `now()` (never the application
  server's clock — avoids any clock-skew risk between the two) —
  computed as `(lease_expires_at > now())` in the same SELECT, exactly
  mirroring services.analysis_history_repository.extend_analysis_job_lease()'s
  own condition.

Either failing raises the new `WebsearchQuotaLeaseInvalidError` (see
its own docstring) — before the reservation-marker insert or any
counter touch, exactly like every other pre-reservation validation
failure above.

**This SELECT now also takes `for update`** (it did not before this
task) — the row-level lock this takes on the specific
`analysis_runs` row, held for the rest of this transaction, is what
makes the lease check genuinely race-safe against a *concurrent*
services.analysis_history_repository.extend_analysis_job_lease()/
complete_analysis_job()/fail_expired_running_analysis_runs() call
landing in the narrow window between this SELECT and this function's
own COMMIT: any of those three would simply block on this row until
this transaction commits or rolls back, then re-evaluate their own
WHERE clause against whatever this transaction actually committed —
never racing against a value this transaction already read and
assumed stays true. Without `for update`, this would only be a
read-committed snapshot taken *at SELECT time*, which a concurrent
writer could still invalidate before this transaction's own commit —
simply reading the two extra columns, without this lock, would not by
itself have been a genuine atomicity fix (see this task's own
completion report in docs/claude-task-handoff.md for why "a Python
SELECT followed by a Python if-check" is explicitly not treated as
'atomic' on its own here).

**What this still does not, and cannot, close** (see the handoff
entry's "保証の限界" section for the full breakdown): the window
between this function's own COMMIT and the actual external API HTTP
call the caller makes immediately afterward. A lease that lapses in
that specific window — after this function has already durably
reserved quota — cannot be un-reserved or un-sent; the underlying
`asyncio.to_thread()`-run HTTP call (see analysis_job_worker.py's own
"Hard constraint" docstring) cannot be interrupted once started. This
task narrows the overall risk window from "up to one heartbeat
interval, or longer if the worker process's own sweep can't run
concurrently" down to "the time between this function's COMMIT and
the next HTTP send" — materially smaller, but not zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    AnalysisQuotaExceededError,
    UsageCounterRequirement,
    _reserve_usage_counters,
    daily_period_start,
    get_connection,
    monthly_period_start,
)
from services.analyze_quota_settings import load_analyze_quota_settings
from services.project_access import ProjectAccessError, can_user_access_analysis_run

logger = logging.getLogger(__name__)

# Must match services/analyze_quota_settings.py's metric keys exactly
# — the only metrics this function will ever reserve. Deliberately a
# closed set, not "any string the caller wants": see this module's
# docstring, item 1. "gemini_external_document" (Task 6-D-4C-2,
# feature/gemini-external-document-supplement) was added alongside the
# original three Task 6-D-2A metrics — see
# migrations/011_add_gemini_external_document_metric.sql for the
# matching CHECK-constraint widening this required. "fact_extraction"
# (Task 6-D-5C-2, feature/claude-fact-extraction-mvp) was added the
# same way — see migrations/012_add_fact_extraction_metric.sql.
WEBSEARCH_METRICS: tuple[str, ...] = (
    "openai_websearch",
    "anthropic_websearch",
    "google_websearch",
    "gemini_external_document",
    "fact_extraction",
)


class WebsearchQuotaInvalidMetricError(Exception):
    """Raised when `metric` is not one of WEBSEARCH_METRICS — a
    programming-error guard (see module docstring item 1), never
    reachable from untrusted input today."""


class WebsearchQuotaRunNotFoundError(Exception):
    """Raised when `analysis_run_id` doesn't exist, doesn't belong to
    `project_id`, or is soft-deleted. Deliberately the same exception
    regardless of which of those is true — a future HTTP-facing caller
    should map this the same way can_user_access_analysis_run()'s own
    callers do (403/404, without distinguishing "doesn't exist" from
    "exists but isn't yours"), so this function doesn't leak which
    case applies to anyone who shouldn't already know."""


class WebsearchQuotaRunNotRunningError(Exception):
    """Raised when `analysis_run_id` exists and belongs to
    `project_id`, but its status isn't 'running'. A websearch
    follow-up only ever makes sense while the synchronous request that
    owns this run is still in flight — reserving quota against an
    already-completed/failed/queued run would be a caller bug, not a
    legitimate retry."""


class WebsearchQuotaAccessDeniedError(Exception):
    """Raised when `user_id` cannot access `project_id` (per
    services.project_access.can_user_access_analysis_run())."""


class WebsearchQuotaLeaseInvalidError(Exception):
    """Task 6-D-5C-4G: raised only when `async_worker_id` was passed
    (i.e. only for an async-worker-originated call — never reachable
    from a synchronous caller, which never passes this parameter) and
    either `analysis_runs.locked_by` does not equal `async_worker_id`
    or `lease_expires_at` is null/not strictly in the future (per the
    database server's own clock). Deliberately a single exception for
    both cases — a caller cannot distinguish "someone else's lease"
    from "my own lease already expired" from the outside, and
    shouldn't need to: either way, this worker no longer has a
    verified right to spend quota against this run right now."""


class WebsearchQuotaAlreadyReservedError(Exception):
    """Raised when (`analysis_run_id`, `metric`) already has a row in
    analysis_run_websearch_reservations (migration 010) — this exact
    run has already reserved this provider's websearch quota once,
    and neither the daily nor monthly counter is touched a second
    time for this call (see module docstring).

    **Does not mean "a Web-search API call already happened" or "may
    happen again for free"** — this module only tracks quota
    bookkeeping, never whether the actual (future) Web-search API was
    called or what it returned. A caller catching this should treat it
    as "do not attempt another websearch follow-up for this run and
    provider", not as license to retry the real API call using the
    reservation already on record.
    """


class WebsearchQuotaReservationError(Exception):
    """Raised on a connection/query failure while reserving websearch
    quota — distinct from AnalysisQuotaExceededError (quota correctly
    enforced, just already exhausted) and from every access/validation
    error above (the request itself was invalid, not failed). Mirrors
    services.analysis_history_repository.AnalysisHistoryReadError: a
    future caller should treat this as a 503, never as "reservation
    succeeded"."""


@dataclass(frozen=True)
class WebsearchQuotaReservation:
    """Returned on a successful reservation — confirmation only
    (no count snapshot; see module docstring on why this stays
    minimal)."""

    analysis_run_id: str
    project_id: str
    metric: str


def reserve_websearch_quota_for_analysis_run(
    *,
    analysis_run_id: str,
    project_id: str,
    user_id: str,
    metric: str,
    async_worker_id: str | None = None,
) -> WebsearchQuotaReservation:
    """Atomically reserves one unit of `metric`'s daily *and* monthly
    websearch quota (Task 6-D-2A) against `analysis_run_id`, after
    validating `metric`, run/project consistency, run status, project
    access, and — only when `async_worker_id` is given — async lease
    ownership (Task 6-D-5C-4G) — see module docstring for the full
    contract, the known same-run/same-provider double-reservation gap,
    and exactly what the lease check does and does not guarantee.

    `async_worker_id`: **omit this entirely for every synchronous
    caller** (the default `None` preserves this function's exact
    pre-existing behavior). Pass the async job worker's own
    `worker_id` for every async-worker-originated call — see
    services/analysis_supplement_orchestrator.py's
    `async_worker_id` parameter and
    services/fact_extraction_provider.py's own, both of which this
    function's async callers thread it through from, ultimately
    sourced from services/analysis_job_worker.py's `worker_id`. Never
    silently infer "this is an async call" from anything else
    (an env var, a global, a thread-local) — see module docstring:
    this parameter must be passed explicitly by every async call site,
    and this task's own test suite verifies every one of them does.

    Raises (never returns falsy/None — every rejection is an
    exception, so a careless caller cannot mistake "reservation
    failed" for "reservation succeeded", per Task 6-D-2B item "4"):

    - WebsearchQuotaInvalidMetricError: `metric` isn't one of
      WEBSEARCH_METRICS.
    - WebsearchQuotaRunNotFoundError: no such run, wrong project, or
      soft-deleted.
    - WebsearchQuotaRunNotRunningError: run exists/matches but isn't
      'running'.
    - WebsearchQuotaAccessDeniedError: `user_id` can't access
      `project_id`.
    - WebsearchQuotaLeaseInvalidError: `async_worker_id` was given and
      either doesn't match `analysis_runs.locked_by`, or the run's
      `lease_expires_at` is null or not strictly in the future. Never
      raised when `async_worker_id` is `None` (every synchronous call).
    - WebsearchQuotaAlreadyReservedError: this exact
      (analysis_run_id, metric) pair already has a reservation on
      record — neither counter is incremented again.
    - AnalysisQuotaExceededError: the daily or monthly limit for
      `metric` is already reached (0 by default — see
      services/analyze_quota_settings.py). Reused as-is (not wrapped)
      so a future caller can handle it exactly like every other
      paid-provider quota rejection in this codebase.
    - WebsearchQuotaReservationError: any other connection/query
      failure. Never silently treated as "quota check skipped, assume
      allowed".

    No auto-refund on a later Web-search *API* failure — see module
    docstring / this task's completion report "5" for why: this
    function only ever meters *attempts*, exactly like the existing
    openai/anthropic/google counters create_running_analysis_run()
    already reserves before calling those providers (never refunded on
    a provider failure either). Refunding on failure would let a
    failing/retried search become free to re-attempt indefinitely,
    defeating the reason this quota exists.
    """
    if metric not in WEBSEARCH_METRICS:
        raise WebsearchQuotaInvalidMetricError(
            f"metric must be one of {WEBSEARCH_METRICS!r}, got {metric!r}"
        )

    quota_settings = load_analyze_quota_settings()
    daily_limit = quota_settings.max_project_daily_by_metric[metric]
    monthly_limit = quota_settings.max_project_monthly_by_metric[metric]
    now = datetime.now(timezone.utc)
    daily_start = daily_period_start(now)
    monthly_start = monthly_period_start(now)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Same project-scoped advisory lock key
                # (hashtextextended(project_id, 0)) as
                # create_running_analysis_run()/create_queued_analysis_run()
                # — see those functions' docstrings for why index 0 is
                # reserved for a project-scoped lock. This function
                # never takes the paired user-scoped lock (index 1)
                # those functions also take, so it can never
                # participate in a reverse-order deadlock with them:
                # it only ever acquires one lock, never two in any
                # order.
                cur.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (project_id,),
                )

                # Task 6-D-5C-4G: `for update` (new) takes a row-level
                # lock on this specific analysis_runs row for the rest
                # of this transaction — see module docstring for why
                # this, not just reading two extra columns, is what
                # actually makes the lease check below race-safe
                # against a concurrent extend_analysis_job_lease()/
                # complete_analysis_job()/fail_expired_running_analysis_runs()
                # call. `locked_by`/`(lease_expires_at > now())` are
                # always selected (harmless for a synchronous caller,
                # which simply never looks at them below).
                cur.execute(
                    "select project_id, status, locked_by, "
                    "(lease_expires_at > now()) as lease_valid "
                    "from analysis_runs where id = %s and deleted_at is null "
                    "for update",
                    (analysis_run_id,),
                )
                row = cur.fetchone()
                if row is None or str(row[0]) != str(project_id):
                    raise WebsearchQuotaRunNotFoundError(
                        f"analysis_run_id={analysis_run_id!r} not found for "
                        f"project_id={project_id!r}"
                    )
                run_status = row[1]
                if run_status != "running":
                    raise WebsearchQuotaRunNotRunningError(
                        f"analysis_run_id={analysis_run_id!r} has status "
                        f"{run_status!r}, expected 'running'"
                    )

                if async_worker_id is not None:
                    locked_by = row[2]
                    lease_valid = row[3]
                    if locked_by != async_worker_id or not lease_valid:
                        raise WebsearchQuotaLeaseInvalidError(
                            f"analysis_run_id={analysis_run_id!r} is not currently "
                            f"leased to async_worker_id={async_worker_id!r} with a "
                            "still-valid lease"
                        )

                if not can_user_access_analysis_run(conn, user_id, analysis_run_id):
                    raise WebsearchQuotaAccessDeniedError(
                        f"user_id={user_id!r} cannot access analysis_run_id={analysis_run_id!r}"
                    )

                # Atomically checks-and-sets the per-(run, metric)
                # dedup marker (migration 010) BEFORE touching
                # analysis_usage_counters at all — see module
                # docstring. "on conflict ... do nothing returning"
                # returns no row exactly when the marker already
                # existed, which is this function's only signal to
                # distinguish "first reservation" from "already
                # reserved"; still inside the same transaction as the
                # advisory lock above and the counter reservation
                # below, so a raise here rolls back cleanly with
                # nothing committed.
                cur.execute(
                    "insert into analysis_run_websearch_reservations "
                    "(analysis_run_id, metric) values (%s, %s) "
                    "on conflict (analysis_run_id, metric) do nothing "
                    "returning analysis_run_id",
                    (analysis_run_id, metric),
                )
                if cur.fetchone() is None:
                    raise WebsearchQuotaAlreadyReservedError(
                        f"analysis_run_id={analysis_run_id!r} has already reserved "
                        f"metric={metric!r}"
                    )

                # Reuses the exact same tested atomic primitive
                # create_running_analysis_run() uses for its own
                # provider counters — see that function's and
                # _reserve_usage_counters()'s own docstrings. Raising
                # AnalysisQuotaExceededError here rolls back this
                # whole transaction (nothing committed yet), so
                # neither counter is left partially incremented.
                _reserve_usage_counters(
                    cur,
                    [
                        UsageCounterRequirement(
                            scope_type="project",
                            scope_id=project_id,
                            metric=metric,
                            period_type="daily",
                            period_start=daily_start,
                            limit=daily_limit,
                        ),
                        UsageCounterRequirement(
                            scope_type="project",
                            scope_id=project_id,
                            metric=metric,
                            period_type="monthly",
                            period_start=monthly_start,
                            limit=monthly_limit,
                        ),
                    ],
                )
            conn.commit()
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
        WebsearchQuotaLeaseInvalidError,
        WebsearchQuotaAlreadyReservedError,
        AnalysisQuotaExceededError,
    ):
        raise
    except ProjectAccessError as exc:
        raise WebsearchQuotaReservationError(
            "failed to check project access while reserving websearch quota"
        ) from exc
    except AnalysisHistoryReadError as exc:
        raise WebsearchQuotaReservationError(
            "failed to open a database connection while reserving websearch quota"
        ) from exc
    except Exception as exc:
        logger.exception("Failed to reserve websearch quota for analysis run")
        raise WebsearchQuotaReservationError(
            "failed to reserve websearch quota for analysis run"
        ) from exc

    return WebsearchQuotaReservation(
        analysis_run_id=str(analysis_run_id), project_id=str(project_id), metric=metric
    )
