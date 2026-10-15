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


# --- run_worker_loop() -------------------------------------------------------


def _fake_settings(poll_interval_seconds=60, lease_seconds=180):
    return type(
        "S",
        (),
        {
            "worker_enabled": True,
            "lease_seconds": lease_seconds,
            "poll_interval_seconds": poll_interval_seconds,
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


def test_generate_worker_id_produces_distinct_ids():
    assert worker.generate_worker_id() != worker.generate_worker_id()
