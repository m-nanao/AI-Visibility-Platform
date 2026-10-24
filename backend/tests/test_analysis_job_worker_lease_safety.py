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

Task 6-D-5C-4D's fix narrows this window (it cannot close it
entirely — see the module's own "Hard constraint" docstring: a call
already in flight cannot be interrupted): process_one_job() now checks
`lease_lost_state["lease_lost"]` immediately before *starting* the
supplement-providers call, and again immediately before *starting* the
fact-extraction call, skipping each entirely once the lease is already
known lost — since the job's result is going to be discarded anyway
(see the `if lease_lost_state["lease_lost"]:` branch that already
skips the completion write).

Never touches a real database and never calls a real external
provider/AI API.
"""

from __future__ import annotations

import asyncio
import time

import services.analysis_job_worker as worker
from services.analysis_history_repository import ClaimedAnalysisJob
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
    """The supplements call itself started before the lease was known
    lost (nothing can interrupt it mid-flight — it already ran to
    completion for real), but by the time control returns to decide
    whether to start fact extraction, the lease-lost check must have
    already caught it."""
    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.0))
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    # The lease is still fine during the (instant) pipeline call, but
    # is lost on every heartbeat tick from then on — which, given a
    # 0.03s heartbeat interval and a 0.3s slow supplements call below,
    # fires at least once while that call is still in flight.
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: False)

    supplement_calls = []

    def slow_supplements(**kwargs):
        supplement_calls.append(1)
        time.sleep(0.3)

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
