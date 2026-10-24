"""Verifies services.analysis_job_worker (Phase 2's background worker)
without ever touching a real database or calling any external AI/paid
API — every repository function
(claim_next_queued_analysis_run()/complete_analysis_job()/
fail_expired_running_analysis_runs()) and main.run_analysis_pipeline()
are monkeypatched directly, mirroring the monkeypatch-at-the-call-site
pattern used throughout this backend's other test files.

These are plain `async def` coroutines exercised via `asyncio.run()`
rather than a pytest-asyncio-style fixture — this project has no
pytest-asyncio dependency, and `asyncio.run()` is sufficient for the
straight-line coroutines under test here.

The one test that runs the *real* (unmocked) run_analysis_pipeline()
end-to-end (test_process_one_job_runs_real_pipeline_without_calling_any_provider)
does so with every provider mode left at its default ("off"/"mock")
and no documents/urls (falling back to the development sample
documents) — exactly the same "no external call" shape POST /analyze
already exercises elsewhere in this test suite.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import services.analysis_job_worker as worker
from services.analysis_history_repository import AnalysisHistoryReadError, ClaimedAnalysisJob


def _run(coro):
    return asyncio.run(coro)


# --- process_one_job() -------------------------------------------------------


def test_process_one_job_returns_false_when_nothing_queued(monkeypatch):
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: None)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is False


def test_process_one_job_completes_successfully(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="11111111-1111-1111-1111-111111111111",
        input_snapshot={"brandName": "Acme", "urls": ["https://example.com"]},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    class _FakeResult:
        def model_dump(self):
            return {"brandName": "Acme"}

        meta = type("Meta", (), {"model_dump": lambda self: {"sections": {}}})()

    import main

    fake_outcome = main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="real", source_summary={}
    )

    pipeline_calls = []

    def fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        return fake_outcome

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)

    complete_calls = []

    def fake_complete(analysis_run_id, **kwargs):
        complete_calls.append((analysis_run_id, kwargs))
        return True

    monkeypatch.setattr(worker, "complete_analysis_job", fake_complete)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["brand_name"] == "Acme"
    assert pipeline_calls[0]["urls"] == ["https://example.com"]

    (completed_id, complete_kwargs) = complete_calls[0]
    assert completed_id == claimed.analysis_run_id
    assert complete_kwargs["worker_id"] == "worker-1"
    assert complete_kwargs["status"] == "completed"
    assert complete_kwargs["result_json"] == {"brandName": "Acme"}
    assert complete_kwargs["meta_json"] == {"sections": {}}
    assert complete_kwargs["error_message"] is None


def test_process_one_job_marks_partial_when_cooccurrence_unavailable(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="22222222-2222-2222-2222-222222222222",
        input_snapshot={"brandName": "Acme", "urls": ["https://bad.example.com"]},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeResult:
        def model_dump(self):
            return {}

        meta = type("Meta", (), {"model_dump": lambda self: {}})()

    fake_outcome = main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="unavailable", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    _run(worker.process_one_job("worker-1", 180))

    assert complete_calls[0]["status"] == "partial"


def test_process_one_job_marks_failed_on_pipeline_input_error(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="33333333-3333-3333-3333-333333333333",
        input_snapshot={"brandName": "Acme", "urls": []},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    def raise_input_error(**kwargs):
        raise main.AnalysisPipelineInputError("urls must not be empty")

    monkeypatch.setattr(main, "run_analysis_pipeline", raise_input_error)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "failed"
    assert complete_calls[0]["result_json"] is None
    assert complete_calls[0]["error_message"] == "urls must not be empty"


def test_process_one_job_marks_failed_on_unexpected_exception_without_crashing(monkeypatch):
    """A bug in the pipeline (or an AI-provider client raising instead
    of reporting its own status/reason) must never escape
    process_one_job() and kill the worker loop."""
    claimed = ClaimedAnalysisJob(
        analysis_run_id="44444444-4444-4444-4444-444444444444",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    def raise_unexpected(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "run_analysis_pipeline", raise_unexpected)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "failed"
    assert complete_calls[0]["result_json"] is None


def test_process_one_job_fails_immediately_when_brand_name_missing(monkeypatch):
    """Defensive handling of a stale/malformed input_snapshot — POST
    /analysis-jobs already requires brandName at creation time, so
    this should never actually happen, but the pipeline must never be
    called with no brand name."""
    claimed = ClaimedAnalysisJob(
        analysis_run_id="55555555-5555-5555-5555-555555555555",
        input_snapshot={"brandName": "   "},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    pipeline_calls = []
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    _run(worker.process_one_job("worker-1", 180))

    assert pipeline_calls == []
    assert complete_calls[0]["status"] == "failed"
    assert complete_calls[0]["error_message"] == "brandName is required"


def test_process_one_job_does_not_crash_when_completion_write_is_discarded(monkeypatch):
    """complete_analysis_job() returning False means the lease was
    lost to a lease-expiry sweep before this write landed (docs/40
    "11.5") — process_one_job() must still return normally (True: a
    job *was* claimed and attempted), not raise."""
    claimed = ClaimedAnalysisJob(
        analysis_run_id="66666666-6666-6666-6666-666666666666",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeResult:
        def model_dump(self):
            return {}

        meta = type("Meta", (), {"model_dump": lambda self: {}})()

    fake_outcome = main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="real", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)
    monkeypatch.setattr(worker, "complete_analysis_job", lambda analysis_run_id, **kwargs: False)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True


def test_process_one_job_does_not_crash_when_completion_save_raises(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="77777777-7777-7777-7777-777777777777",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeResult:
        def model_dump(self):
            return {}

        meta = type("Meta", (), {"model_dump": lambda self: {}})()

    fake_outcome = main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="real", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)

    def raise_read_error(analysis_run_id, **kwargs):
        raise AnalysisHistoryReadError("db is down")

    monkeypatch.setattr(worker, "complete_analysis_job", raise_read_error)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True


def test_process_one_job_runs_real_pipeline_without_calling_any_provider(monkeypatch):
    """End-to-end with the *real* (unmocked) run_analysis_pipeline().
    The job's input_snapshot has no documents/urls/provider-mode
    overrides, so (exactly like a bare POST /analyze request with no
    env-configured API keys) it falls back to development sample
    documents with every provider resolving to "off"/"mock" and never
    making an HTTP request. ChatGPT/Common Crawl/URL-fetch are also
    structurally unreachable here: ChatGPT is skipped outright while
    aiOverviewMode is "mock" (the default, see main.py's own comment
    at that branch), Common Crawl defaults to mode="off", and
    fetch_url_texts() is only reached on the `urls is not None` branch
    — none of which this input triggers — so monkeypatching all three
    to raise if called is a safe, meaningful assertion. Claude/Gemini
    are NOT similarly monkeypatched: unlike ChatGPT, main.py calls
    them unconditionally (see its own comment there) and relies on
    them resolving to mode="off" internally (no CLAUDE_API_KEY/
    GEMINI_API_KEY configured in this test environment) to make no
    real HTTP call — the same assumption every other /analyze test in
    this suite already makes without monkeypatching those two
    functions out."""
    claimed = ClaimedAnalysisJob(
        analysis_run_id="88888888-8888-8888-8888-888888888888",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    def _never_call(*args, **kwargs):
        raise AssertionError("this AI provider function must not be called")

    monkeypatch.setattr(main, "build_chatgpt_observation", _never_call)
    monkeypatch.setattr(main, "fetch_url_texts", _never_call)
    monkeypatch.setattr(main, "search_common_crawl_domain", _never_call)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "completed"
    assert complete_calls[0]["result_json"]["brandName"] == "Acme"


# --- heartbeat ---------------------------------------------------------------


def _slow_fake_pipeline(sleep_seconds, **kwargs):
    """A fake run_analysis_pipeline() that actually blocks (real
    time.sleep(), executed in a real thread via asyncio.to_thread() —
    exactly like the real pipeline) long enough for the heartbeat loop
    to get at least one scheduling opportunity to fire."""
    import main

    time.sleep(sleep_seconds)

    class _FakeResult:
        def model_dump(self):
            return {}

        meta = type("Meta", (), {"model_dump": lambda self: {}})()

    return main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="real", source_summary={}
    )


def test_heartbeat_extends_lease_while_pipeline_is_still_running(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.3))

    extend_calls = []

    def fake_extend(analysis_run_id, **kwargs):
        extend_calls.append((analysis_run_id, kwargs))
        return True

    monkeypatch.setattr(worker, "extend_analysis_job_lease", fake_extend)
    monkeypatch.setattr(worker, "complete_analysis_job", lambda analysis_run_id, **kwargs: True)

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.05))

    assert result is True
    assert len(extend_calls) >= 1
    assert extend_calls[0][0] == claimed.analysis_run_id
    assert extend_calls[0][1]["worker_id"] == "worker-1"
    assert extend_calls[0][1]["lease_seconds"] == 180


def test_heartbeat_stops_sending_updates_after_job_completes(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.1))

    extend_calls = []
    monkeypatch.setattr(
        worker,
        "extend_analysis_job_lease",
        lambda analysis_run_id, **kwargs: extend_calls.append(1) or True,
    )
    monkeypatch.setattr(worker, "complete_analysis_job", lambda analysis_run_id, **kwargs: True)

    async def go():
        await worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03)
        count_right_after = len(extend_calls)
        await asyncio.sleep(0.15)  # well past several more would-be heartbeat ticks
        return count_right_after, len(extend_calls)

    count_right_after, count_later = _run(go())

    assert count_later == count_right_after  # no further heartbeats after the job finished


def test_process_one_job_skips_completion_write_when_heartbeat_detects_lease_lost(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.3))
    # The very first heartbeat tick reports the lease is already gone.
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: False)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.05))

    assert result is True
    assert complete_calls == []  # never attempted — skipped once lease loss was detected


def test_heartbeat_transient_db_error_does_not_mark_lease_lost(monkeypatch):
    """A single transient AnalysisHistoryReadError while extending must
    not be treated the same as a genuine lease loss — it's retried at
    the next heartbeat tick, not escalated immediately (docs/40's "DB
    障害時に無制限の更新リトライをしない" constraint is about not
    retrying in a tight loop, not about giving up on the very first
    hiccup)."""
    claimed = ClaimedAnalysisJob(
        analysis_run_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _slow_fake_pipeline(0.2))

    def flaky_extend(analysis_run_id, **kwargs):
        raise AnalysisHistoryReadError("transient failure")

    monkeypatch.setattr(worker, "extend_analysis_job_lease", flaky_extend)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03))

    assert result is True
    # The completion write was still attempted normally — a transient
    # heartbeat error alone never counts as "lease lost".
    assert len(complete_calls) == 1
    assert complete_calls[0]["status"] == "completed"


# --- run_worker_loop() -------------------------------------------------------


def _fake_settings(poll_interval_seconds=60, lease_seconds=180, heartbeat_interval_seconds=30):
    return type(
        "S",
        (),
        {
            "worker_enabled": True,
            "lease_seconds": lease_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
        },
    )()


def test_run_worker_loop_returns_immediately_when_stop_event_already_set(monkeypatch):
    monkeypatch.setattr(worker, "load_analysis_jobs_settings", lambda: _fake_settings())
    monkeypatch.setattr(worker, "fail_expired_running_analysis_runs", lambda: [])
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: None)

    async def go():
        stop_event = asyncio.Event()
        stop_event.set()
        await worker.run_worker_loop(stop_event, worker_id="test-worker")

    _run(go())  # must return promptly, not hang


def test_run_worker_loop_sweeps_expired_leases_before_claiming(monkeypatch):
    """Runs the loop as a background task against a *long* poll
    interval (so it would never wake up on its own within the test's
    lifetime) and stops it from the test coroutine itself after a
    short real-time sleep — `stop_event.set()` must be called from the
    event loop thread, never from inside a mocked repository call that
    executes via asyncio.to_thread() in a worker thread (asyncio.Event
    is not thread-safe)."""
    call_order = []
    monkeypatch.setattr(worker, "load_analysis_jobs_settings", lambda: _fake_settings())

    def fake_fail_expired():
        call_order.append("fail_expired")
        return []

    def fake_claim(**kwargs):
        call_order.append("claim")
        return None

    monkeypatch.setattr(worker, "fail_expired_running_analysis_runs", fake_fail_expired)
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", fake_claim)

    async def go():
        stop_event = asyncio.Event()
        task = asyncio.create_task(worker.run_worker_loop(stop_event, worker_id="test-worker"))
        await asyncio.sleep(0.05)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    _run(go())

    assert call_order[:2] == ["fail_expired", "claim"]


def test_run_worker_loop_continues_after_repository_error(monkeypatch):
    """A transient DB error while sweeping expired leases must not
    stop the loop for the rest of the process's lifetime."""
    attempts = []
    # A very short poll interval so several iterations happen within
    # the test's brief sleep below, proving the loop kept polling
    # after the first iteration's error rather than merely not
    # crashing on it.
    monkeypatch.setattr(
        worker, "load_analysis_jobs_settings", lambda: _fake_settings(poll_interval_seconds=0.01)
    )

    def fake_fail_expired():
        attempts.append(1)
        if len(attempts) == 1:
            raise AnalysisHistoryReadError("transient failure")
        return []

    monkeypatch.setattr(worker, "fail_expired_running_analysis_runs", fake_fail_expired)
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: None)

    async def go():
        stop_event = asyncio.Event()
        task = asyncio.create_task(worker.run_worker_loop(stop_event, worker_id="test-worker"))
        await asyncio.sleep(0.2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    _run(go())

    assert len(attempts) >= 2  # the loop survived the first error and polled again


# --- start_worker() / stop_worker() -----------------------------------------


def test_start_worker_creates_no_task_when_disabled(monkeypatch):
    monkeypatch.setattr(
        worker,
        "load_analysis_jobs_settings",
        lambda: type("S", (), {"worker_enabled": False, "lease_seconds": 180})(),
    )

    handle = worker.start_worker()

    assert handle.task is None


def test_start_worker_creates_task_when_enabled(monkeypatch):
    monkeypatch.setattr(
        worker,
        "load_analysis_jobs_settings",
        lambda: type(
            "S", (), {"worker_enabled": True, "lease_seconds": 180, "poll_interval_seconds": 5}
        )(),
    )

    async def fake_loop(stop_event, worker_id=None):
        await stop_event.wait()

    monkeypatch.setattr(worker, "run_worker_loop", fake_loop)

    async def go():
        handle = worker.start_worker()
        assert handle.task is not None
        await worker.stop_worker(handle)

    _run(go())


def test_stop_worker_is_noop_when_task_is_none():
    async def go():
        handle = worker.WorkerHandle(task=None, stop_event=asyncio.Event())
        await worker.stop_worker(handle)  # must not raise

    _run(go())


def test_stop_worker_cancels_task_that_ignores_stop_event(monkeypatch):
    monkeypatch.setattr(worker, "SHUTDOWN_GRACE_SECONDS", 0.05)

    async def go():
        stop_event = asyncio.Event()

        async def stubborn_loop():
            while True:
                await asyncio.sleep(10)

        task = asyncio.create_task(stubborn_loop())
        handle = worker.WorkerHandle(task=task, stop_event=stop_event)

        await worker.stop_worker(handle)

        assert task.cancelled() or task.done()

    _run(go())


def test_stop_worker_logs_warning_when_in_flight_job_does_not_stop_in_time(monkeypatch, caplog):
    """Explicit regression guard for the honesty requirement in
    stop_worker()'s docstring: when the grace period elapses, this
    must be logged as a warning (not silently swallowed) — the thread
    behind an in-flight to_thread() pipeline call keeps running
    regardless of what this function does next, and an operator
    reading logs needs to know that happened."""
    monkeypatch.setattr(worker, "SHUTDOWN_GRACE_SECONDS", 0.05)

    async def go():
        stop_event = asyncio.Event()

        async def stubborn_loop():
            while True:
                await asyncio.sleep(10)

        task = asyncio.create_task(stubborn_loop())
        handle = worker.WorkerHandle(task=task, stop_event=stop_event)

        with caplog.at_level("WARNING", logger="services.analysis_job_worker"):
            await worker.stop_worker(handle)

    _run(go())

    assert any("did not stop within" in record.message for record in caplog.records)


def test_generate_worker_id_produces_distinct_ids():
    assert worker.generate_worker_id() != worker.generate_worker_id()


# --- Task 6-D-5C-2 (feature/claude-fact-extraction-mvp) integration ------
#
# attempt_fact_extraction() is called from inside process_one_job()'s
# successful-pipeline branch — these tests verify it is called with
# the right arguments (including the new ClaimedAnalysisJob.project_id/
# created_by_user_id fields), that its result is folded into
# outcome.result.factExtraction (and therefore into the saved
# result_json), and that an unexpected exception there never fails the
# job.


def test_attempt_fact_extraction_is_called_with_claimed_project_and_user_ids(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="99999999-9999-9999-9999-999999999999",
        input_snapshot={"brandName": "Acme", "urls": ["https://example.com"]},
        attempt_count=1,
        project_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        created_by_user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeMeta:
        def model_dump(self):
            return {"sections": {}}

    class _FakeResult:
        aiOverviewComparison = ["card-placeholder"]
        factExtraction = None
        meta = _FakeMeta()

        def model_dump(self):
            return {"brandName": "Acme", "factExtraction": self.factExtraction}

    fake_result = _FakeResult()
    fake_outcome = main.AnalysisPipelineOutcome(
        result=fake_result, cooccurrence_status="real", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)
    monkeypatch.setattr(worker, "complete_analysis_job", lambda analysis_run_id, **kwargs: True)

    fact_extraction_calls = []

    def fake_attempt(**kwargs):
        fact_extraction_calls.append(kwargs)
        return "FACT_EXTRACTION_RESULT_SENTINEL"

    monkeypatch.setattr(worker, "attempt_fact_extraction", fake_attempt)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert len(fact_extraction_calls) == 1
    call = fact_extraction_calls[0]
    assert call["analysis_run_id"] == claimed.analysis_run_id
    assert call["project_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert call["user_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert call["ai_overview_comparison"] == ["card-placeholder"]
    assert fake_result.factExtraction == "FACT_EXTRACTION_RESULT_SENTINEL"


def test_fact_extraction_result_is_included_in_saved_result_json(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
        project_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        created_by_user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeMeta:
        def model_dump(self):
            return {"sections": {}}

    class _FakeResult:
        aiOverviewComparison = []
        factExtraction = None
        meta = _FakeMeta()

        def model_dump(self):
            return {"brandName": "Acme", "factExtraction": self.factExtraction}

    fake_result = _FakeResult()
    fake_outcome = main.AnalysisPipelineOutcome(
        result=fake_result, cooccurrence_status="real", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: {"status": "disabled"})

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["result_json"]["factExtraction"] == {"status": "disabled"}


def test_fact_extraction_failure_never_fails_the_job(monkeypatch):
    claimed = ClaimedAnalysisJob(
        analysis_run_id="d2d2d2d2-d2d2-d2d2-d2d2-d2d2d2d2d2d2",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
        project_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        created_by_user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)

    import main

    class _FakeMeta:
        def model_dump(self):
            return {"sections": {}}

    class _FakeResult:
        aiOverviewComparison = []
        factExtraction = None
        meta = _FakeMeta()

        def model_dump(self):
            return {"brandName": "Acme"}

    fake_outcome = main.AnalysisPipelineOutcome(
        result=_FakeResult(), cooccurrence_status="real", source_summary={}
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "attempt_fact_extraction", _raise)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "completed"
