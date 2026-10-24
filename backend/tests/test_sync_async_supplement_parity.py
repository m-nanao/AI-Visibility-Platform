"""Task 6-D-5C-4D item 2: given identical mock pipeline output,
identical provider responses, and identical quota conditions, the
synchronous authenticated /analyze path and the asynchronous job
worker must produce the same aiOverviewComparison / supplement-meta /
factExtraction fields — since both now call the exact same shared
functions (services.analysis_supplement_orchestrator.run_sync_supplement_providers()
and services.fact_extraction_provider.attempt_fact_extraction()) in
the same fixed order.

Both call sites are monkeypatched with the *same* fake functions (not
just equivalent ones) so this test proves the two wiring sites pass
through arguments and fold results back into AnalysisResult
identically — it does not re-verify each provider's own internal
logic (already covered elsewhere).

Non-deterministic/identity fields excluded from the comparison, with
reasons: `analysisRunId` (a fresh UUID per path/run, assigned by
different repository functions), `meta.generatedAt` (a timestamp), and
`aiOverviewComparison`/`cooccurrenceRanking`/etc.'s identity-only
content coming from build_dummy_analysis() itself is kept but is
already identical between the two paths since both use the exact same
fake pipeline outcome.

Never touches a real database and never calls a real external
provider/AI API.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import main
import services.analysis_job_worker as worker
from main import app
from models import (
    AIOverviewComparisonItem,
    ChatGptProviderInfo,
    ChatGptWebsearchProviderInfo,
    ClaudeProviderInfo,
    Document,
    FactExtractionResult,
    GeminiProviderInfo,
)
from services.analysis_history_repository import ClaimedAnalysisJob, SyncAnalysisRunReservation
from services.jwt_auth import AuthenticatedUser
from services.mock_analysis import build_dummy_analysis

client = TestClient(app)

WEB_FETCH_DOCUMENT = Document(
    id="doc-1",
    sourceType="web_fetch",
    sourceUrl="https://acme.example.com",
    fetchedAt="2026-10-24T00:00:00Z",
    text="hello",
)


def _build_fake_outcome(brand_name: str):
    result = build_dummy_analysis(brand_name)
    result.meta.chatgptProvider = ChatGptProviderInfo(
        mode="openai", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    result.meta.claudeProvider = ClaudeProviderInfo(
        mode="anthropic", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    result.meta.geminiProvider = GeminiProviderInfo(
        mode="google", status="real", reason="ok", environment="api",
        recognitionLevel="unidentified", promptVersion="no_search_v1",
    )
    return main.AnalysisPipelineOutcome(
        result=result,
        cooccurrence_status="real",
        source_summary={},
        web_fetch_documents=[WEB_FETCH_DOCUMENT],
    )


def _fake_orchestrator(*, brand_name, result, web_fetch_documents, **kwargs):
    item = AIOverviewComparisonItem(
        platform="ChatGPT (OpenAI API, Web検索補完)", mentioned=True, rank=None,
        summary=f"{brand_name} websearch summary, {len(web_fetch_documents)} doc(s)",
        observationMethod="websearch_supplement",
    )
    result.meta.chatgptWebsearchProvider = ChatGptWebsearchProviderInfo(
        status="real", reason="ok", searched=True
    )
    result.aiOverviewComparison = [*result.aiOverviewComparison, item]


def _fake_fact_extraction(**kwargs):
    return FactExtractionResult(status="real", extractionModel="claude-sonnet-5-5")


def _relevant_fields(result_dict: dict) -> dict:
    return {
        "aiOverviewComparison": result_dict["aiOverviewComparison"],
        "chatgptWebsearchProvider": result_dict["meta"]["chatgptWebsearchProvider"],
        "claudeWebsearchProvider": result_dict["meta"]["claudeWebsearchProvider"],
        "geminiWebsearchProvider": result_dict["meta"]["geminiWebsearchProvider"],
        "geminiExternalDocumentProvider": result_dict["meta"]["geminiExternalDocumentProvider"],
        "factExtraction": result_dict["factExtraction"],
    }


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _run_sync(monkeypatch) -> dict:
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, project_id: True)
    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id="sync-run-id", created=True, status="running", locked_by="sync:tok"
        ),
    )
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _build_fake_outcome(kwargs["brand_name"]))
    monkeypatch.setattr(main, "run_sync_supplement_providers", _fake_orchestrator)
    monkeypatch.setattr(main, "attempt_fact_extraction", lambda **kwargs: _fake_fact_extraction(**kwargs))
    monkeypatch.setattr(main, "complete_analysis_job", lambda run_id, **kwargs: True)

    response = client.post(
        "/analyze",
        json={"brandName": "Acme", "projectId": "p1", "requestId": "req-1"},
        headers={"Authorization": "Bearer a.b.c"},
    )
    assert response.status_code == 200
    return response.json()


def _run_async(monkeypatch) -> dict:
    claimed = ClaimedAnalysisJob(
        analysis_run_id="async-run-id",
        input_snapshot={"brandName": "Acme"},
        attempt_count=1,
        project_id="p1",
        created_by_user_id="user-1",
    )
    monkeypatch.setattr(worker, "claim_next_queued_analysis_run", lambda **kwargs: claimed)
    monkeypatch.setattr(main, "run_analysis_pipeline", lambda **kwargs: _build_fake_outcome(kwargs["brand_name"]))
    monkeypatch.setattr(worker, "run_sync_supplement_providers", _fake_orchestrator)
    monkeypatch.setattr(worker, "attempt_fact_extraction", lambda **kwargs: _fake_fact_extraction(**kwargs))
    monkeypatch.setattr(worker, "extend_analysis_job_lease", lambda analysis_run_id, **kwargs: True)

    complete_calls = []
    monkeypatch.setattr(
        worker,
        "complete_analysis_job",
        lambda analysis_run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    result = asyncio.run(worker.process_one_job("worker-1", 180))
    assert result is True
    return complete_calls[0]["result_json"]


def test_sync_and_async_produce_identical_supplement_and_fact_extraction_fields(monkeypatch):
    sync_result = _run_sync(monkeypatch)
    async_result = _run_async(monkeypatch)

    assert _relevant_fields(sync_result) == _relevant_fields(async_result)
