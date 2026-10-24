"""Verifies Task 6-D-5C-4C (feature/async-analysis-supplements):
services.analysis_job_worker.process_one_job() now calls the same
shared services.analysis_supplement_orchestrator.run_sync_supplement_providers()
the synchronous authenticated /analyze path uses (Task 6-D-5C-4B),
right after run_analysis_pipeline() returns and right before the
existing attempt_fact_extraction() call — never after
complete_analysis_job() marks the run completed/partial/failed.

Never touches a real database and never calls a real external
provider/AI API. Most tests monkeypatch
worker.run_sync_supplement_providers directly (its own per-provider
gating/quota/wiring logic is already covered by
tests/test_analysis_supplement_orchestrator.py and each provider's own
test_*_provider.py/test_*_client.py); one test
(test_all_four_supplements_disabled_by_default_makes_no_extra_call)
deliberately leaves it unmocked to prove the real default-disabled
path makes no DB/HTTP call on its own from inside the worker either.
"""

from __future__ import annotations

import asyncio
import time

import services.analysis_job_worker as worker
from services.analysis_history_repository import ClaimedAnalysisJob
from services.mock_analysis import build_dummy_analysis

CLAIMED = ClaimedAnalysisJob(
    analysis_run_id="11111111-1111-1111-1111-111111111111",
    input_snapshot={"brandName": "Acme", "urls": ["https://acme.example.com"]},
    attempt_count=1,
    project_id="22222222-2222-2222-2222-222222222222",
    created_by_user_id="33333333-3333-3333-3333-333333333333",
)


def _run(coro):
    return asyncio.run(coro)


def _stub_pipeline(monkeypatch, *, result=None, web_fetch_documents=None):
    import main

    fake_result = result if result is not None else build_dummy_analysis("Acme")
    fake_outcome = main.AnalysisPipelineOutcome(
        result=fake_result,
        cooccurrence_status="real",
        source_summary={},
        web_fetch_documents=web_fetch_documents or [],
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: fake_outcome)
    return fake_result, fake_outcome


def _stub_claim(monkeypatch, claimed=CLAIMED):
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)
    # Task 6-D-5C-4E: process_one_job() now actively re-verifies (and
    # extends) the lease immediately before the supplement providers
    # and before fact extraction (see
    # _reverify_lease_before_next_step()) — every test in this file
    # that isn't specifically about lease behavior needs this to
    # succeed so the step it's actually testing gets a chance to run
    # at all. A test that cares about lease behavior itself
    # overrides this afterward.
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: True)


def _stub_complete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: calls.append(kwargs) or True,
    )
    return calls


# --- wiring: called with the right arguments --------------------------------


def test_run_sync_supplement_providers_called_with_claimed_ids_and_web_fetch_documents(
    monkeypatch,
):
    from models import Document

    docs = [
        Document(
            id="doc-1",
            sourceType="web_fetch",
            sourceUrl="https://acme.example.com",
            fetchedAt="2026-10-24T00:00:00Z",
            text="hello",
        )
    ]
    fake_result, _ = _stub_pipeline(monkeypatch, web_fetch_documents=docs)
    _stub_claim(monkeypatch)
    _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)

    calls = []

    def fake_orchestrator(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(worker, "run_sync_supplement_providers", fake_orchestrator)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert len(calls) == 1
    call = calls[0]
    assert call["brand_name"] == "Acme"
    assert call["result"] is fake_result
    assert call["web_fetch_documents"] == docs
    assert call["analysis_run_id"] == CLAIMED.analysis_run_id
    assert call["project_id"] == CLAIMED.project_id
    assert call["user_id"] == CLAIMED.created_by_user_id


def test_run_sync_supplement_providers_called_exactly_once_per_job(monkeypatch):
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)

    calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: calls.append(1)
    )

    _run(worker.process_one_job("worker-1", 180))

    assert len(calls) == 1


# --- ordering: supplements -> fact extraction -> complete_analysis_job -----


def test_supplements_run_before_fact_extraction_and_before_completion(monkeypatch):
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    order = []

    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: order.append("supplements")
    )
    monkeypatch.setattr(
        worker, "attempt_fact_extraction", lambda **kwargs: order.append("fact_extraction")
    )
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: order.append("complete") or True,
    )

    _run(worker.process_one_job("worker-1", 180))

    assert order == ["supplements", "fact_extraction", "complete"]


def test_fact_extraction_sees_items_appended_by_supplements(monkeypatch):
    """Mirrors the sync path's own ordering guarantee: FactExtraction
    reads result.aiOverviewComparison as already built by the four
    supplements above it — this must hold in the worker too."""
    from models import AIOverviewComparisonItem

    no_search_card = AIOverviewComparisonItem(
        platform="ChatGPT (OpenAI API)", mentioned=True, rank=None, summary="no_search_card"
    )
    websearch_card = AIOverviewComparisonItem(
        platform="ChatGPT (OpenAI API, Web検索補完)", mentioned=True, rank=None,
        summary="websearch_supplement_card", observationMethod="websearch_supplement",
    )

    fake_result, _ = _stub_pipeline(monkeypatch)
    fake_result.aiOverviewComparison = [no_search_card]
    _stub_claim(monkeypatch)
    _stub_complete(monkeypatch)

    def fake_orchestrator(*, result, **kwargs):
        result.aiOverviewComparison = [*result.aiOverviewComparison, websearch_card]

    monkeypatch.setattr(worker, "run_sync_supplement_providers", fake_orchestrator)

    fact_extraction_calls = []

    def fake_attempt(**kwargs):
        fact_extraction_calls.append(kwargs)
        return None

    monkeypatch.setattr(worker, "attempt_fact_extraction", fake_attempt)

    _run(worker.process_one_job("worker-1", 180))

    assert fact_extraction_calls[0]["ai_overview_comparison"] == [no_search_card, websearch_card]


# --- all four disabled by default: no extra call from inside the worker ----


def test_all_four_supplements_disabled_by_default_makes_no_extra_call(monkeypatch):
    """Deliberately does NOT mock run_sync_supplement_providers (nor
    any of the four attempt_*_supplement functions it calls, nor
    reserve_websearch_quota_for_analysis_run) — proves the real,
    default-disabled gate inside each provider makes zero DB/HTTP
    calls when reached from inside the worker, exactly like the sync
    path's own equivalent test."""
    for env_var in (
        "CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED",
        "CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED",
        "GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED",
        "GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED",
    ):
        monkeypatch.delenv(env_var, raising=False)

    from models import ChatGptProviderInfo, ClaudeProviderInfo, GeminiProviderInfo

    fake_result = build_dummy_analysis("Acme")
    # A recognitionLevel must be present for each no-search observation
    # or every gate short-circuits at "not_attempted" before ever
    # reaching the ENABLED check this test wants to exercise — mirrors
    # tests/test_analysis_supplement_orchestrator.py's own
    # _result_with_recognition_levels() helper.
    fake_result.meta.chatgptProvider = ChatGptProviderInfo(
        mode="openai", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    fake_result.meta.claudeProvider = ClaudeProviderInfo(
        mode="anthropic", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    fake_result.meta.geminiProvider = GeminiProviderInfo(
        mode="google", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    _stub_pipeline(monkeypatch, result=fake_result)
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert fake_result.meta.chatgptWebsearchProvider.status == "disabled"
    assert fake_result.meta.claudeWebsearchProvider.status == "disabled"
    assert fake_result.meta.geminiWebsearchProvider.status == "disabled"
    assert fake_result.meta.geminiExternalDocumentProvider.status == "disabled"
    assert complete_calls[0]["status"] == "completed"


# --- failure isolation: never fails the job ---------------------------------


def test_supplement_orchestrator_exception_never_fails_the_job(monkeypatch):
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "run_sync_supplement_providers", _raise)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "completed"


# --- heartbeat/lease safety: the orchestrator call runs off the event loop -


def _slow_orchestrator(sleep_seconds, **kwargs):
    """A fake run_sync_supplement_providers() that actually blocks
    (real time.sleep(), executed in a real thread via
    asyncio.to_thread() — exactly like the real four-provider HTTP
    calls) long enough for the heartbeat loop to get at least one
    scheduling opportunity to fire while it runs."""
    time.sleep(sleep_seconds)


def test_heartbeat_keeps_extending_lease_while_supplements_are_still_running(monkeypatch):
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: _slow_orchestrator(0.3)
    )

    extend_calls = []
    monkeypatch.setattr(
        worker,
        "extend_analysis_job_lease",
        lambda analysis_run_id, **kwargs: extend_calls.append((analysis_run_id, kwargs)) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.05))

    assert result is True
    assert len(extend_calls) >= 1
    assert extend_calls[0][0] == CLAIMED.analysis_run_id


def test_lease_lost_during_supplements_skips_completion_write(monkeypatch):
    """Mirrors test_process_one_job_skips_completion_write_when_heartbeat_detects_lease_lost
    in tests/test_analysis_job_worker.py, but with the slow step now
    inside the supplement orchestrator call instead of the pipeline
    call — the lease-lost detection must work the same way regardless
    of which blocking step is still in flight when it happens."""
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: _slow_orchestrator(0.2)
    )
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: False)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = _run(worker.process_one_job("worker-1", 180, heartbeat_interval_seconds=0.03))

    assert result is True
    assert complete_calls == []  # completion write skipped — lease already known lost


# --- backward compatibility: old-shaped results never crash the worker -----


def test_result_missing_supplement_meta_fields_does_not_crash_the_job(monkeypatch):
    """A pre-Task-6-D-5C-4B-shaped result object without
    chatgptProvider/claudeProvider/geminiProvider set (e.g. a stale
    fixture, or a provider that genuinely never ran) must not crash the
    real run_sync_supplement_providers() call — each provider attempt
    is wrapped in its own try/except (Task 6-D-5C-4B), so an
    AttributeError while reading result.meta.chatgptProvider etc. is
    swallowed there, never escaping to fail the job."""

    class _BareMeta:
        def model_dump(self):
            return {}

    class _BareResult:
        aiOverviewComparison: list = []
        factExtraction = None
        meta = _BareMeta()

        def model_dump(self):
            return {"brandName": "Acme"}

    bare_result = _BareResult()
    _stub_pipeline(monkeypatch, result=bare_result)
    _stub_claim(monkeypatch)
    complete_calls = _stub_complete(monkeypatch)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: None)

    result = _run(worker.process_one_job("worker-1", 180))

    assert result is True
    assert complete_calls[0]["status"] == "completed"


# --- Task 6-D-5C-4G: async_worker_id wiring ---------------------------------


def test_worker_id_is_passed_as_async_worker_id_to_both_supplements_and_fact_extraction(
    monkeypatch,
):
    """Task 6-D-5C-4G item "所有者情報の欠落によるガード迂回を防ぐ": the
    worker must pass its own worker_id as async_worker_id to both
    calls — never omit it (which would silently fall back to the
    weaker, lease-unaware synchronous contract for that call)."""
    _stub_pipeline(monkeypatch)
    _stub_claim(monkeypatch)
    _stub_complete(monkeypatch)

    supplement_calls = []
    monkeypatch.setattr(
        worker, "run_sync_supplement_providers", lambda **kwargs: supplement_calls.append(kwargs)
    )
    fact_extraction_calls = []
    monkeypatch.setattr(
        worker,
        "attempt_fact_extraction",
        lambda **kwargs: fact_extraction_calls.append(kwargs),
    )

    _run(worker.process_one_job("worker-42", 180))

    assert supplement_calls[0]["async_worker_id"] == "worker-42"
    assert fact_extraction_calls[0]["async_worker_id"] == "worker-42"
