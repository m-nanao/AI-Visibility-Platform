"""Verifies main.py's `lifespan` actually starts/stops Phase 2's
background worker (services.analysis_job_worker.start_worker()/
stop_worker()) around the FastAPI app's own startup/shutdown — see
docs/40_async_analysis_jobs_design.md "12.1".

FastAPI's/Starlette's TestClient only runs the app's `lifespan` when
used as a context manager (`with TestClient(app) as client:`) —
every *other* test file in this backend instantiates `TestClient(app)`
without `with`, which is exactly why none of them ever trigger the
worker (confirmed: the full existing suite passes whether or not
ANALYSIS_JOBS_WORKER_ENABLED happens to be set, since lifespan simply
never runs for them). This file is the one place that deliberately
uses the context-manager form, specifically to exercise lifespan
itself — `start_worker()`/`stop_worker()` are monkeypatched here so
this never touches a real database or starts a real polling loop.
"""

from fastapi.testclient import TestClient

import main
import services.analysis_job_worker as worker


def test_lifespan_starts_and_stops_the_worker(monkeypatch):
    calls = []

    def fake_start_worker():
        calls.append("start")
        return worker.WorkerHandle(task=None, stop_event=None)

    async def fake_stop_worker(handle):
        calls.append("stop")

    monkeypatch.setattr(worker, "start_worker", fake_start_worker)
    monkeypatch.setattr(worker, "stop_worker", fake_stop_worker)

    with TestClient(main.app) as client:
        assert calls == ["start"]
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == ["start", "stop"]


def test_lifespan_does_not_start_worker_task_when_disabled(monkeypatch):
    """An end-to-end sanity check (no monkeypatch of start_worker/
    stop_worker themselves this time) that the default, worker-disabled
    configuration really does produce no task — the same guarantee
    services/analysis_job_worker.py's own
    test_start_worker_creates_no_task_when_disabled already verifies
    in isolation, exercised here through the actual lifespan wiring."""
    monkeypatch.delenv("ANALYSIS_JOBS_WORKER_ENABLED", raising=False)

    handles = []
    original_start_worker = worker.start_worker

    def recording_start_worker():
        handle = original_start_worker()
        handles.append(handle)
        return handle

    monkeypatch.setattr(worker, "start_worker", recording_start_worker)

    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert len(handles) == 1
    assert handles[0].task is None
