"""Verifies Task 6-D-5C-4D's lease-lost guard around the four
supplement providers and fact extraction inside
services.analysis_job_worker.process_one_job().

Background (see docs/claude-task-handoff.md's Task 6-D-5C-4D entry for
the full write-up): services.websearch_quota_reservation's
reserve_websearch_quota_for_analysis_run() only checks
`analysis_runs.status == 'running'`, never `lease_expires_at` — so a
provider call already attempted after this worker's heartbeat has
detected lease loss could, in principle, still reserve quota and make
one real (eventually-discarded) paid API call, because nothing has
flipped the row's status away from 'running' yet (that only happens
once fail_expired_running_analysis_runs() next sweeps it, which cannot
happen while this same single-worker-process loop is still blocked
inside this very process_one_job() call).

Task 6-D-5C-4D's fix narrowed this window by checking the heartbeat's
own (passive, up-to-heartbeat-interval-stale) `lease_lost_state["lease_lost"]`
flag before starting each step. Task 6-D-5C-4E strengthens this
further: `_reverify_lease_before_next_step()` now actively calls
extend_analysis_job_lease() again, synchronously, immediately before
each step — the exact same atomic check the heartbeat uses, reused
as-is (no new repository function, no signature change, no
migration) — fail-closed on any DB uncertainty. Neither version closes
the gap entirely (it cannot — see the module's own "Hard constraint"
docstring: a call already in flight cannot be interrupted, and
reserve_websearch_quota_for_analysis_run() itself never checks
lease_expires_at at all — see docs/claude-task-handoff.md's Task
6-D-5C-4E entry for the full analysis and the follow-up options that
would be needed to close it completely).

Never touches a real database and never calls a real external
provider/AI API.
"""

from __future__ import annotations

import asyncio
import time

import services.analysis_job_worker as worker
from services.analysis_history_repository import AnalysisHistoryReadError, ClaimedAnalysisJob
from services.mock_analysis import build_dummy_analysis

CLAIMED = ClaimedAnalysisJob(
    analysis_run_id="44444444-4444-4444-4444-444444444444",
    input_snapshot={"brandName": "Acme"},
    attempt_count=1,
    project_id="55555555-5555-5555-5555-555555555555",
    created_by_user_id="66666666-6666-6666-6666-666666666666",
)


def _run(coro):
    return asyncio.run(coro)


def _stub_claim(monkeypatch):
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: CLAIMED)


def _stub_complete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: calls.append(kwargs) or True,
    )
    return calls


def _slow_fake_pipeline(sleep_seconds, **kwargs):
    """A fake run_analysis_pipeline() that actually blocks (real
    time.sleep(), executed in a real thread via asyncio.to_thread()) —
    mirrors tests/test_analysis_job_worker.py's own helper of the same
    shape."""
    import main

    time.sleep(sleep_seconds)
    return main.AnalysisPipelineOutcome(
        result=build_dummy_analysis("Acme"), cooccurrence_status="real", source_summary={}
    )


def test_lease_lost_during_pipeline_skips_both_supplements_and_fact_extraction(monkeypatch):
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.3))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    # Lease is lost on the very first heartbeat tick, well before the
    # 0.3s pipeline sleep finishes.
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: False)

    supplement_calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: supplement_calls.append(1)
    )
    fact_extraction_calls = []
    monkeypatch.setattr(
        worker, "attempt_fact_extraction", lambda **kwargs: fact_extraction_calls.append(1)
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03))

    assert result is True
    assert supplement_calls == []
    assert fact_extraction_calls == []
    assert complete_calls == []  # completion write skipped — lease already known lost


def test_lease_lost_during_supplements_still_skips_fact_extraction(monkeypatch):
    """The supplements call itself started while the lease was still
    genuinely valid — the pre-step re-verification (Task 6-D-5C-4E)
    lets it start, and once started it cannot be interrupted mid-flight
    (it already ran to completion for real) — but the lease is lost
    *during* that call, and by the time control returns to decide
    whether to start fact extraction, the next re-verification must
    catch it.

    Deterministic by construction, not by sleep-counting (per this
    task's "sleepだけに依存する不安定なテストを増やさない" constraint):
    `lease_state["lost"]` flips to True only once the supplements call
    has actually started, so the pre-supplements re-verification is
    guaranteed to see it still healthy, and the pre-fact-extraction
    re-verification (and every heartbeat tick during the sleep) is
    guaranteed to see it already lost — regardless of exact timing."""
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.0))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)

    lease_state = {"lost": False}

    def flaky_extend(analysis_run_id, **kwargs):
        return not lease_state["lost"]

    monkeypatch.setattr(worker, "extend_analysis_job_lease", flaky_extend)

    supplement_calls = []

    def slow_supplements(**kwargs):
        supplement_calls.append(1)
        lease_state["lost"] = True  # the lease is lost while this call is in flight
        time.sleep(0.2)

    monkeypatch.setattr(worker, "run_sync_supplement_providers", slow_supplements)
    fact_extraction_calls = []
    monkeypatch.setattr(
        worker, "attempt_fact_extraction", lambda **kwargs: fact_extraction_calls.append(1)
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03))

    assert result is True
    assert supplement_calls == [1]  # already in flight when lease loss was detected — ran anyway
    assert fact_extraction_calls == []  # but the *next* step was correctly skipped
    assert complete_calls == []


def test_lease_owner_mismatch_is_indistinguishable_from_expiry_and_skips_supplements(monkeypatch):
    """extend_analysis_job_lease()'s single boolean return conflates
    "lease expired" and "a different worker_id now owns this row" —
    both are simply `False` from this worker's point of view (see that
    function's own WHERE clause: `locked_by = worker_id AND status =
    'running' AND lease_expires_at > now()`, any one of which failing
    produces the same False). This test exists to document that
    equivalence explicitly, not because the worker-side code branches
    differently for the two cases — it does not, and should not: both
    mean "I no longer safely own this job"."""
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.0))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    # Simulates a different worker_id now holding the lease (as far as
    # this worker can tell, this looks exactly like an expired lease).
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: False)

    supplement_calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: supplement_calls.append(1)
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert supplement_calls == []
    assert complete_calls == []


def test_db_failure_while_reverifying_lease_fails_closed(monkeypatch):
    """Task 6-D-5C-4D item "DB確認失敗時のfail-closed動作": a
    connection failure while re-verifying the lease must be treated
    exactly like an explicit lease loss — never as "assume it's still
    valid and proceed". This is deliberately stricter than the
    heartbeat's own transient-error tolerance (see
    tests/test_analysis_job_worker.py's
    test_heartbeat_transient_db_error_does_not_mark_lease_lost): the
    heartbeat gets another chance on its next tick, but this check
    runs exactly once, right before committing to a new, potentially
    paid step — there is no "next tick" to retry on before that
    decision is made, so uncertainty must resolve to "do not proceed"."""
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.0))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)

    def raise_db_error(analysis_run_id, **kwargs):
        raise AnalysisHistoryReadError("connection failed")

    monkeypatch.setattr(worker, "extend_analysis_job_lease", raise_db_error)

    supplement_calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: supplement_calls.append(1)
    )
    fact_extraction_calls = []
    monkeypatch.setattr(
        worker, "attempt_fact_extraction", lambda **kwargs: fact_extraction_calls.append(1)
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert supplement_calls == []
    assert fact_extraction_calls == []
    assert complete_calls == []


def test_lease_not_lost_runs_both_supplements_and_fact_extraction_normally(monkeypatch):
    """Sanity check / regression guard: the new checks must not skip
    anything when the lease is healthy throughout — mirrors the
    ordering test in tests/test_analysis_job_worker_supplements.py."""
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.0))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: True)

    supplement_calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: supplement_calls.append(1)
    )
    fact_extraction_calls = []
    monkeypatch.setattr(
        worker, "attempt_fact_extraction", lambda **kwargs: fact_extraction_calls.append(1)
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03))

    assert result is True
    assert supplement_calls == [1]
    assert fact_extraction_calls == [1]
    assert complete_calls[0]["status"] == "completed"
