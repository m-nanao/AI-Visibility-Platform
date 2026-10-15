"""Phase 2 background worker for async analysis jobs — see
docs/40_async_analysis_jobs_design.md "12. Workerの実装方法とRender上の
ライフサイクル".

Runs entirely inside this same FastAPI/uvicorn process (no new
service, no new infra — see docs/40 "3"), started/stopped by main.py's
`lifespan` context manager. Gated by `ANALYSIS_JOBS_WORKER_ENABLED`
(services/analysis_jobs_settings.py, default False) — completely
inert when off: `start_worker()` returns immediately without creating
any asyncio task, and none of claim_next_queued_analysis_run()/
complete_analysis_job()/fail_expired_running_analysis_runs() are ever
called, so a database that hasn't had migration 006 applied yet is
never queried by this module at all while the flag is off.

MVP concurrency model (docs/40 "11.2"): at most one job is executed at
a time *by this process* — the polling loop claims and fully completes
one job before claiming the next. If more than one uvicorn worker
process (or more than one Render instance) runs this code
simultaneously, each runs its own independent loop; correctness across
them is guaranteed by the database (claim_next_queued_analysis_run()'s
`for update skip locked`), not by any assumption of a single process —
see that function's docstring.

The actual analysis pipeline (main.run_analysis_pipeline()) is
synchronous/blocking code (the existing ChatGPT/Claude/Gemini/
DataForSEO/Common Crawl HTTP clients are not asyncio-based — see
docs/40 "12.2"). Every blocking call this module makes (both the
pipeline itself and every repository function, which open their own
synchronous psycopg connections) is wrapped in `asyncio.to_thread()`
so the FastAPI event loop — and therefore every other concurrent
request this process serves, including GET /analysis-jobs/{id} — is
never blocked for the ~100s a full pipeline run can take.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from dataclasses import dataclass

from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    claim_next_queued_analysis_run,
    complete_analysis_job,
    fail_expired_running_analysis_runs,
)
from services.analysis_jobs_settings import load_analysis_jobs_settings

logger = logging.getLogger(__name__)

# How long stop_worker() waits for an in-flight job to reach a natural
# stopping point before cancelling the task outright — intentionally
# short (this is NOT "wait for the job to finish", see docs/40 "12.5":
# no graceful job-draining is implemented in this MVP). A job
# interrupted by cancellation is handled the same way any other
# abandoned job is: its lease eventually expires and
# fail_expired_running_analysis_runs() transitions it to 'failed'.
SHUTDOWN_GRACE_SECONDS = 5


def generate_worker_id() -> str:
    """A diagnostic identifier for this process's worker instance
    (hostname + pid + a short random suffix, so two processes on the
    same host — or even two restarts of the same process — never
    collide) — stored in analysis_runs.locked_by so a stuck/failed job
    can be traced back to which worker last touched it (docs/40
    "11.3"). Not a secret, not used for access control."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


async def process_one_job(worker_id: str, lease_seconds: int) -> bool:
    """Claims and fully executes at most one queued job. Returns True
    if a job was claimed (regardless of whether it ended up
    'completed'/'partial'/'failed'), False if there was nothing queued
    to claim — the caller (run_worker_loop()) uses this to decide
    whether to poll again immediately or wait out the poll interval.

    Imports main.run_analysis_pipeline()/AnalysisPipelineInputError
    lazily (inside this function, not at module import time) — see
    main.py's `lifespan` for why: this module is only ever imported
    *after* main.py has fully finished loading (lifespan imports it
    lazily too), so a top-level import here would work in practice,
    but keeping it function-local removes any dependency on that
    ordering being preserved by a future refactor.
    """
    from main import AnalysisPipelineInputError, run_analysis_pipeline

    claimed = await asyncio.to_thread(
        claim_next_queued_analysis_run, worker_id=worker_id, lease_seconds=lease_seconds
    )
    if claimed is None:
        return False

    logger.info(
        "analysis job claimed: analysis_run_id=%s worker_id=%s attempt=%d",
        claimed.analysis_run_id,
        worker_id,
        claimed.attempt_count,
    )

    snapshot = claimed.input_snapshot if isinstance(claimed.input_snapshot, dict) else {}
    brand_name = (snapshot.get("brandName") or "").strip()

    status: str
    result_json: dict | None = None
    meta_json: dict | None = None
    error_message: str | None = None

    if not brand_name:
        # Should not happen — POST /analysis-jobs already requires a
        # non-empty brandName at creation time (see main.py's
        # create_analysis_job()) — but a stale/malformed
        # input_snapshot is handled the same defensive way
        # run_analysis_pipeline()'s own validation is: fail the job,
        # never crash the worker loop.
        status = "failed"
        error_message = "brandName is required"
    else:
        try:
            # The pipeline itself is synchronous/blocking (see module
            # docstring) — run it off the event loop.
            outcome = await asyncio.to_thread(
                run_analysis_pipeline,
                brand_name=brand_name,
                documents=snapshot.get("documents"),
                urls=snapshot.get("urls"),
                common_crawl_mode=snapshot.get("commonCrawlMode"),
                common_crawl_domain=snapshot.get("commonCrawlDomain"),
                ai_overview_mode_override=snapshot.get("aiOverviewMode"),
                chatgpt_mode_override=snapshot.get("chatgptMode"),
                claude_mode_override=snapshot.get("claudeMode"),
                gemini_mode_override=snapshot.get("geminiMode"),
            )
        except AnalysisPipelineInputError as exc:
            status = "failed"
            error_message = str(exc)
        except Exception:
            # A genuinely unexpected failure (bug, or an AI-provider
            # client raising instead of reporting its own status/
            # reason — see run_analysis_pipeline()'s docstring). Never
            # let this escape process_one_job() and kill the worker
            # loop; the job is marked failed and the loop continues.
            logger.exception(
                "unexpected error running analysis pipeline for job %s",
                claimed.analysis_run_id,
            )
            status = "failed"
            error_message = "unexpected error while running analysis"
        else:
            status = (
                "partial" if outcome.cooccurrence_status == "unavailable" else "completed"
            )
            result_json = outcome.result.model_dump()
            meta_json = outcome.result.meta.model_dump()

    try:
        completed = await asyncio.to_thread(
            complete_analysis_job,
            claimed.analysis_run_id,
            worker_id=worker_id,
            status=status,
            result_json=result_json,
            meta_json=meta_json,
            error_message=error_message,
        )
    except AnalysisHistoryReadError:
        # The job genuinely ran (or failed) but its outcome could not
        # be saved — see docs/40 "13.3": the result is lost, the job
        # will eventually be reaped by fail_expired_running_analysis_runs()
        # once its lease passes. Logged, not raised — the loop must
        # keep running.
        logger.exception(
            "failed to save completion for job %s (status=%s)",
            claimed.analysis_run_id,
            status,
        )
        return True

    if not completed:
        # This worker's lease had already expired and the row was
        # reaped to 'failed' by a (possibly different) poll cycle
        # before this write landed — see
        # complete_analysis_job()'s docstring and docs/40 "11.5". The
        # result computed above is simply discarded; it is never
        # retried or written anywhere else.
        logger.warning(
            "job %s completion discarded: lease no longer owned by worker %s "
            "(stale write avoided, status attempted=%s)",
            claimed.analysis_run_id,
            worker_id,
            status,
        )
    else:
        logger.info(
            "analysis job finished: analysis_run_id=%s worker_id=%s status=%s",
            claimed.analysis_run_id,
            worker_id,
            status,
        )

    return True


async def run_worker_loop(stop_event: asyncio.Event, *, worker_id: str | None = None) -> None:
    """The continuous polling loop — started as a single asyncio task
    by start_worker(), runs until `stop_event` is set. Each iteration:
    sweep expired leases first (so an abandoned job is reaped before
    this cycle might otherwise claim right past it), then try to claim
    and execute one job; if nothing was claimed, wait out the poll
    interval (or until `stop_event` is set, whichever comes first)
    before trying again.

    A failure in either the sweep or a single job attempt is logged
    and the loop continues — a transient DB hiccup must never
    permanently stop the worker for the rest of the process's
    lifetime. An exception escaping this function entirely (which
    should not happen, given the try/excepts below, but is caught here
    too as a last resort) is logged at CRITICAL so it is diagnosable
    from Render logs even though nothing awaits this task's result
    under normal operation (docs/40 "12.4").
    """
    worker_id = worker_id or generate_worker_id()
    settings = load_analysis_jobs_settings()
    logger.info(
        "analysis job worker started: worker_id=%s lease_seconds=%d poll_interval_seconds=%d",
        worker_id,
        settings.lease_seconds,
        settings.poll_interval_seconds,
    )

    try:
        while not stop_event.is_set():
            try:
                expired_ids = await asyncio.to_thread(fail_expired_running_analysis_runs)
                if expired_ids:
                    logger.warning(
                        "analysis job(s) failed due to expired worker lease: %s",
                        expired_ids,
                    )
            except AnalysisHistoryReadError:
                logger.exception("failed to sweep expired analysis job leases")

            try:
                did_work = await process_one_job(worker_id, settings.lease_seconds)
            except AnalysisHistoryReadError:
                logger.exception("failed to claim next analysis job")
                did_work = False

            if not did_work:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=settings.poll_interval_seconds
                    )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.critical(
            "analysis job worker crashed and will not resume until the process "
            "restarts: worker_id=%s",
            worker_id,
            exc_info=True,
        )
        raise
    finally:
        logger.info("analysis job worker stopped: worker_id=%s", worker_id)


@dataclass
class WorkerHandle:
    """Returned by start_worker(); pass to stop_worker() on shutdown.
    `task` is None when the worker was disabled (ANALYSIS_JOBS_WORKER_ENABLED
    is not set) — stop_worker() on such a handle is a safe no-op."""

    task: asyncio.Task | None
    stop_event: asyncio.Event


def start_worker() -> WorkerHandle:
    """Starts the background polling task if
    ANALYSIS_JOBS_WORKER_ENABLED=true; otherwise logs that it's
    disabled and returns a handle with no task — see docs/40 "7"/"12.1".
    Called once, from main.py's `lifespan`, at process startup."""
    settings = load_analysis_jobs_settings()
    stop_event = asyncio.Event()

    if not settings.worker_enabled:
        logger.info(
            "analysis job worker disabled (ANALYSIS_JOBS_WORKER_ENABLED is not set) "
            "— no background task started, no worker-related table/column will be queried"
        )
        return WorkerHandle(task=None, stop_event=stop_event)

    task = asyncio.create_task(run_worker_loop(stop_event))
    return WorkerHandle(task=task, stop_event=stop_event)


async def stop_worker(handle: WorkerHandle) -> None:
    """Signals the worker loop to stop and waits briefly for it to
    reach a stopping point, cancelling it outright if it doesn't (see
    SHUTDOWN_GRACE_SECONDS and docs/40 "12.5" — no graceful job-draining
    is implemented). A no-op when `handle.task` is None (worker was
    disabled). Swallows the task's own CancelledError (expected on a
    forced cancellation) but lets any other exception the task raised
    propagate, so a worker crash is still visible to whatever called
    this (main.py's lifespan, during app shutdown)."""
    handle.stop_event.set()
    if handle.task is None:
        return

    try:
        await asyncio.wait_for(handle.task, timeout=SHUTDOWN_GRACE_SECONDS)
    except asyncio.TimeoutError:
        handle.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await handle.task
