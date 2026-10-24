"""Mocked unit tests for
services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() (Task 6-D-2B,
feature/websearch-quota-reservation).

Never touches a real database: `get_connection`/
`can_user_access_analysis_run`/`_reserve_usage_counters` are all
monkeypatched at this module's own namespace (each is imported by
name into services.websearch_quota_reservation, so patching the name
there — not the original module it came from — is what actually
takes effect). The genuine-concurrency/atomicity claims this module
makes about analysis_usage_counters are proven separately, against a
real disposable PostgreSQL instance, by
tests/test_websearch_quota_reservation_integration.py.
"""

import pytest

import services.websearch_quota_reservation as wq
from services.analysis_history_repository import AnalysisQuotaExceededError
from services.project_access import ProjectAccessError

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_PROJECT_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"
RUN_ID = "44444444-4444-4444-4444-444444444444"


class _FakeCursor:
    def __init__(self, fetchone_results):
        # Consumed in call order: the run lookup's fetchone() is
        # always first, then the reservation-marker insert's own
        # fetchone() (migration 010's "on conflict ... returning"),
        # then — when _reserve_usage_counters() is NOT monkeypatched
        # (test_default_zero_limit_rejects_the_reservation below) —
        # its own daily/monthly fetchone() calls consume the remaining
        # entries in order. The advisory-lock SELECT never calls
        # fetchone() at all.
        self._fetchone_results = list(fetchone_results)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        if not self._fetchone_results:
            return None
        return self._fetchone_results.pop(0)


class _FakeConnection:
    def __init__(self, fetchone_results):
        self.cur = _FakeCursor(fetchone_results)
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


_RESERVATION_INSERTED = (RUN_ID,)
_RESERVATION_ALREADY_EXISTED = None


def _mock_connection(
    monkeypatch,
    *,
    run_row,
    reservation_insert_result=_RESERVATION_INSERTED,
    extra_fetchone_results=None,
):
    fetchone_results = [run_row, reservation_insert_result, *(extra_fetchone_results or [])]
    conn = _FakeConnection(fetchone_results)
    monkeypatch.setattr(wq, "get_connection", lambda: conn)
    return conn


def _mock_access(monkeypatch, *, allowed: bool):
    monkeypatch.setattr(
        wq, "can_user_access_analysis_run", lambda conn, user_id, analysis_run_id: allowed
    )


def _mock_reserve_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        wq,
        "_reserve_usage_counters",
        lambda cur, counters: calls.append(counters),
    )
    return calls


def _mock_reserve_exceeded(monkeypatch, *, metric: str, period_type: str):
    def _raise(cur, counters):
        raise AnalysisQuotaExceededError(
            scope_type="project",
            scope_id=PROJECT_ID,
            metric=metric,
            period_type=period_type,
            period_start=None,
            limit=0,
        )

    monkeypatch.setattr(wq, "_reserve_usage_counters", _raise)


# --- metric validation -------------------------------------------------


def test_rejects_a_metric_outside_the_fixed_websearch_set(monkeypatch):
    """Task 6-D-2B item 1: the caller must not be able to reserve an
    arbitrary metric string. Also proves no DB connection is even
    attempted for an invalid metric."""

    def fail_if_called():
        raise AssertionError("get_connection() should not be called for an invalid metric")

    monkeypatch.setattr(wq, "get_connection", fail_if_called)

    with pytest.raises(wq.WebsearchQuotaInvalidMetricError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID, project_id=PROJECT_ID, user_id=USER_ID, metric="openai"
        )


@pytest.mark.parametrize("metric", wq.WEBSEARCH_METRICS)
def test_accepts_every_metric_in_the_fixed_websearch_set(monkeypatch, metric):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    result = wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID, project_id=PROJECT_ID, user_id=USER_ID, metric=metric
    )

    assert result.metric == metric
    assert result.analysis_run_id == RUN_ID
    assert result.project_id == PROJECT_ID


# --- run / project consistency -----------------------------------------


def test_rejects_when_the_run_does_not_exist(monkeypatch):
    _mock_connection(monkeypatch, run_row=None)
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaRunNotFoundError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )


def test_rejects_when_the_run_belongs_to_a_different_project(monkeypatch):
    """The run genuinely exists, but under OTHER_PROJECT_ID — passing
    PROJECT_ID must still be rejected rather than silently reserving
    quota against the wrong project's counters."""
    _mock_connection(monkeypatch, run_row=(OTHER_PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaRunNotFoundError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )
    assert reserve_calls == []


@pytest.mark.parametrize("status", ["queued", "completed", "partial", "failed"])
def test_rejects_when_the_run_is_not_running(monkeypatch, status):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, status))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaRunNotRunningError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )
    assert reserve_calls == []


# --- authorization -------------------------------------------------------


def test_rejects_when_the_user_cannot_access_the_project(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=False)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaAccessDeniedError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )
    assert reserve_calls == []


def test_run_lookup_happens_before_the_access_check(monkeypatch):
    """A nonexistent run is rejected as WebsearchQuotaRunNotFoundError
    even when the access check would have denied it too — the run
    lookup is strictly cheaper and happens first, mirroring this
    module's own documented validation order."""
    _mock_connection(monkeypatch, run_row=None)

    def fail_if_called(conn, user_id, analysis_run_id):
        raise AssertionError("can_user_access_analysis_run should not be reached")

    monkeypatch.setattr(wq, "can_user_access_analysis_run", fail_if_called)

    with pytest.raises(wq.WebsearchQuotaRunNotFoundError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )


# --- duplicate-reservation prevention (migration 010) -------------------


def test_rejects_a_duplicate_reservation_for_the_same_run_and_metric(monkeypatch):
    """Task 6-D-2B follow-up item 6: a second reservation attempt for
    the same (analysis_run_id, metric) must be rejected, and must
    never reach _reserve_usage_counters() — proving the daily/monthly
    counters are never incremented a second time."""
    _mock_connection(
        monkeypatch,
        run_row=(PROJECT_ID, "running"),
        reservation_insert_result=_RESERVATION_ALREADY_EXISTED,
    )
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaAlreadyReservedError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )
    assert reserve_calls == []


def test_no_commit_on_a_duplicate_reservation(monkeypatch):
    conn = _mock_connection(
        monkeypatch,
        run_row=(PROJECT_ID, "running"),
        reservation_insert_result=_RESERVATION_ALREADY_EXISTED,
    )
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaAlreadyReservedError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )

    assert conn.committed is False


def test_first_reservation_for_a_run_and_metric_succeeds(monkeypatch):
    _mock_connection(
        monkeypatch,
        run_row=(PROJECT_ID, "running"),
        reservation_insert_result=_RESERVATION_INSERTED,
    )
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    result = wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID, project_id=PROJECT_ID, user_id=USER_ID, metric="openai_websearch"
    )

    assert result.metric == "openai_websearch"
    assert len(reserve_calls) == 1


# --- quota enforcement ---------------------------------------------------


def test_default_zero_limit_rejects_the_reservation(monkeypatch):
    """Task 6-D-2A's default: every websearch metric starts at 0 —
    reserve_websearch_quota_for_analysis_run() must therefore reject
    by default too, with no env vars configured."""
    for name in (
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI_WEBSEARCH",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_OPENAI_WEBSEARCH",
    ):
        monkeypatch.delenv(name, raising=False)
    # Do NOT mock _reserve_usage_counters here — exercise the real
    # function so this test actually proves the limit=0 rejection
    # path, not just that this test's own mock was configured to
    # raise. Its daily-counter INSERT...WHERE %s > 0 guard produces no
    # candidate row when limit=0, so fetchone() must return None here
    # (never the run-lookup row) for this to faithfully simulate real
    # PostgreSQL behavior.
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"), extra_fetchone_results=[None])
    _mock_access(monkeypatch, allowed=True)

    with pytest.raises(AnalysisQuotaExceededError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )


def test_quota_exceeded_error_propagates_unwrapped(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_exceeded(monkeypatch, metric="google_websearch", period_type="daily")

    with pytest.raises(AnalysisQuotaExceededError) as excinfo:
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="google_websearch",
        )
    assert excinfo.value.metric == "google_websearch"
    assert excinfo.value.period_type == "daily"


def test_reserves_both_daily_and_monthly_counters_together(monkeypatch):
    """Both counters must be requested in a single
    _reserve_usage_counters() call (one atomic transaction), never as
    two separate calls — see module docstring on why that matters for
    "no partial increment"."""
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID, project_id=PROJECT_ID, user_id=USER_ID, metric="anthropic_websearch"
    )

    assert len(reserve_calls) == 1
    counters = reserve_calls[0]
    assert len(counters) == 2
    period_types = {c.period_type for c in counters}
    assert period_types == {"daily", "monthly"}
    assert all(c.metric == "anthropic_websearch" for c in counters)
    assert all(c.scope_type == "project" for c in counters)
    assert all(c.scope_id == PROJECT_ID for c in counters)


def test_commit_only_happens_after_a_successful_reservation(monkeypatch):
    conn = _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID, project_id=PROJECT_ID, user_id=USER_ID, metric="openai_websearch"
    )

    assert conn.committed is True


def test_no_commit_when_the_reservation_is_rejected(monkeypatch):
    conn = _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_exceeded(monkeypatch, metric="openai_websearch", period_type="monthly")

    with pytest.raises(AnalysisQuotaExceededError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )

    assert conn.committed is False


# --- DB / access-check error handling ------------------------------------


def test_project_access_error_is_wrapped(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running"))

    def _raise(conn, user_id, analysis_run_id):
        raise ProjectAccessError("boom")

    monkeypatch.setattr(wq, "can_user_access_analysis_run", _raise)

    with pytest.raises(wq.WebsearchQuotaReservationError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )


def test_get_connection_failure_is_wrapped(monkeypatch):
    def _raise():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(wq, "get_connection", _raise)

    with pytest.raises(wq.WebsearchQuotaReservationError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
        )


# --- Task 6-D-5C-4G: async lease validation (omitted entirely when
# async_worker_id is None, i.e. every synchronous caller) -----------------
#
# `run_row` here is a 4-tuple (project_id, status, locked_by,
# lease_valid) — matching the widened SELECT this task added
# (`select project_id, status, locked_by, (lease_expires_at > now())
# as lease_valid ... for update`). Genuine row-level-lock concurrency
# safety is proven separately, against a real PostgreSQL instance, by
# tests/test_websearch_quota_reservation_integration.py — these are
# pure Python-branching unit tests only.

WORKER_ID = "worker-abc-123"
OTHER_WORKER_ID = "worker-xyz-789"


def test_sync_caller_omitting_async_worker_id_never_checks_the_lease(monkeypatch):
    """The default (`async_worker_id=None`, i.e. every existing
    synchronous call site) must behave byte-for-byte like before this
    task — even against a run_row whose lease columns would fail the
    check if it were ever evaluated (locked_by=None, lease invalid)."""
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", None, False))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    result = wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        metric="openai_websearch",
        # async_worker_id omitted entirely.
    )

    assert result.metric == "openai_websearch"


def test_async_reservation_succeeds_with_a_matching_valid_lease(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", WORKER_ID, True))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    result = wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        metric="openai_websearch",
        async_worker_id=WORKER_ID,
    )

    assert result.metric == "openai_websearch"


def test_async_reservation_rejected_when_lease_expired(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", WORKER_ID, False))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
            async_worker_id=WORKER_ID,
        )
    assert reserve_calls == []


def test_async_reservation_rejected_on_worker_id_mismatch(monkeypatch):
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", OTHER_WORKER_ID, True))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
            async_worker_id=WORKER_ID,
        )
    assert reserve_calls == []


def test_async_reservation_rejected_when_lease_is_null(monkeypatch):
    """`lease_valid` is SQL `NULL` (surfaced as Python `None`, not
    `False`) whenever `lease_expires_at is null` — `not None` is
    falsy, so this must reject exactly like an expired lease."""
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", WORKER_ID, None))
    _mock_access(monkeypatch, allowed=True)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
            async_worker_id=WORKER_ID,
        )
    assert reserve_calls == []


def test_async_lease_check_happens_before_the_access_check(monkeypatch):
    """Mirrors test_run_lookup_happens_before_the_access_check's own
    reasoning: the lease check is cheaper (no further DB call) than
    can_user_access_analysis_run(), so it happens first — a request
    with both an invalid lease and no project access is reported as
    the lease problem, not access denial."""
    _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", OTHER_WORKER_ID, True))
    _mock_access(monkeypatch, allowed=False)
    reserve_calls = _mock_reserve_success(monkeypatch)

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
            async_worker_id=WORKER_ID,
        )
    assert reserve_calls == []


def test_async_db_failure_while_checking_run_is_wrapped_the_same_way(monkeypatch):
    """The widened SELECT (now also fetching locked_by/lease_valid and
    taking `for update`) fails the same way any other connection/query
    error in this function already does — never silently treated as
    "lease check skipped, assume valid"."""

    def _raise():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(wq, "get_connection", _raise)

    with pytest.raises(wq.WebsearchQuotaReservationError):
        wq.reserve_websearch_quota_for_analysis_run(
            analysis_run_id=RUN_ID,
            project_id=PROJECT_ID,
            user_id=USER_ID,
            metric="openai_websearch",
            async_worker_id=WORKER_ID,
        )


def test_async_select_now_takes_for_update(monkeypatch):
    """Confirms the actual SQL text includes `for update` — the
    mechanism that makes the lease check race-safe (see this
    function's own docstring); a mock can't prove the locking
    *behavior* (see the integration test for that), but it can prove
    the statement that provides it is actually being sent."""
    conn = _mock_connection(monkeypatch, run_row=(PROJECT_ID, "running", WORKER_ID, True))
    _mock_access(monkeypatch, allowed=True)
    _mock_reserve_success(monkeypatch)

    wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        metric="openai_websearch",
        async_worker_id=WORKER_ID,
    )

    run_lookup_query = conn.cur.queries[1][0]  # [0] is the advisory-lock SELECT
    assert "for update" in run_lookup_query.lower()
    assert "locked_by" in run_lookup_query.lower()
    assert "lease_expires_at" in run_lookup_query.lower()
