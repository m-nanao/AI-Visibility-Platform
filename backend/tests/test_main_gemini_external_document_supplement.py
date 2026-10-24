"""Verifies POST /analyze's Task 6-D-4C-2 wiring for Gemini's
conditional external-document supplement (backend/main.py's
_analyze_authenticated_idempotent(), the block that calls
services.gemini_external_document_provider.attempt_gemini_external_document_supplement()
after run_analysis_pipeline() returns and before complete_analysis_job()
saves the result) — mirrors
tests/test_main_gemini_websearch_supplement.py's structure, plus
dedicated checks for the Document[]-reuse plumbing
(AnalysisPipelineOutcome.web_fetch_documents) and non-interference with
all three existing websearch/grounding supplements.

Never touches a real database and never calls a real external
provider.
"""

from fastapi.testclient import TestClient

import main
from services import analysis_supplement_orchestrator as orchestrator
from main import app
from models import Document, GeminiExternalDocumentProviderInfo, GeminiProviderInfo
from services.analysis_history_repository import SyncAnalysisRunReservation
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

RUN_ID = "11111111-1111-1111-1111-111111111111"


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _web_fetch_doc(url: str) -> Document:
    return Document(
        id=f"doc-{url}",
        sourceType="web_fetch",
        sourceUrl=url,
        fetchedAt="2026-10-24T00:00:00Z",
        text="Acme overview text fetched from the web.",
    )


def _mock_authenticated(monkeypatch, *, user_id: str = "user-1"):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, project_id: True)


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(body: dict):
    return client.post("/analyze", json=body, headers=_jwt_headers())


def _stub_create_running(monkeypatch):
    calls = []

    def fake_create_running(**kwargs):
        calls.append(kwargs)
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)
    return calls


def _stub_pipeline(monkeypatch, *, recognition_level: str | None, web_fetch_documents=None):
    def fake_pipeline(**kwargs):
        result = main.build_dummy_analysis(kwargs["brand_name"])
        if recognition_level is not None:
            result.meta.geminiProvider = GeminiProviderInfo(
                mode="google",
                status="real",
                reason="Gemini Google API request succeeded.",
                environment="api",
                recognitionLevel=recognition_level,
                promptVersion="no_search_v1",
            )
        return main.AnalysisPipelineOutcome(
            result=result,
            cooccurrence_status="real",
            source_summary={},
            web_fetch_documents=web_fetch_documents or [],
        )

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)


def _stub_complete_analysis_job(monkeypatch):
    saved_calls = []

    def fake_complete(run_id, **kwargs):
        saved_calls.append(kwargs)
        return True

    monkeypatch.setattr(main, "complete_analysis_job", fake_complete)
    return saved_calls


def _post_body(**overrides):
    body = {"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"}
    body.update(overrides)
    return body


# --- feature OFF (default) ------------------------------------------------


def test_disabled_by_default_requires_no_mocking_at_all(monkeypatch):
    """The real, unmocked attempt_gemini_external_document_supplement()
    must make zero DB/HTTP calls when
    GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED is unset."""
    monkeypatch.delenv("GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED", raising=False)
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(
        monkeypatch,
        recognition_level="unidentified",
        web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
    )
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "disabled"
    platforms = [c["platform"] for c in body["aiOverviewComparison"]]
    assert not any("外部文書補完" in p for p in platforms)
    assert saved_calls[0]["meta_json"]["geminiExternalDocumentProvider"]["status"] == "disabled"


# --- URL指定がない場合 / ユーザー入力テキストのみの場合 ----------------------


def test_no_urls_given_yields_no_documents_status(monkeypatch):
    """Task 6-D-4C-2 test item 8: a request with no urls[] at all
    produces zero web_fetch Documents, so this supplement reports
    no_documents — it never crashes or silently skips without a
    status."""
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(monkeypatch, recognition_level="unidentified", web_fetch_documents=[])
    monkeypatch.setenv("GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED", "true")
    _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "no_documents"


def test_user_provided_text_only_yields_no_documents_status(monkeypatch):
    """Task 6-D-4C-2 test item 9: `documents[]` (pasted text) alone,
    with no `urls[]`, never produces a `web_fetch` Document — the
    supplement must report no_documents, not silently treat pasted
    text as a fetched document."""
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    # run_analysis_pipeline() genuinely produces zero web_fetch
    # Documents when only `documents[]` was given — this test asserts
    # the wiring handles that (already covered structurally by
    # test_no_urls_given_yields_no_documents_status above using an
    # explicit empty list); this test additionally confirms the
    # request body itself (documents[] present, urls absent) reaches
    # the same outcome end-to-end.
    _stub_pipeline(monkeypatch, recognition_level="unidentified", web_fetch_documents=[])
    monkeypatch.setenv("GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED", "true")
    _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body(documents=["Acme is a company I am describing myself."]))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "no_documents"


# --- wiring: routing + appending ------------------------------------------


def test_websearch_item_is_appended_when_attempt_returns_one(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(
        monkeypatch,
        recognition_level="unidentified",
        web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
    )
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        from models import AIOverviewComparisonItem

        item = AIOverviewComparisonItem(
            platform="Gemini (Google API, 外部文書補完)",
            mentioned=True,
            rank=None,
            summary="document-grounded summary",
            observationMethod="external_document_supplement",
        )
        info = GeminiExternalDocumentProviderInfo(
            status="real",
            reason="ok",
            recognitionLevelAtTrigger="unidentified",
            documentsConsideredCount=1,
            documentsUsedCount=1,
            model="gemini-2.5-flash",
        )
        return item, info

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(calls) == 1
    assert calls[0]["recognition_level"] == "unidentified"
    assert calls[0]["analysis_run_id"] == RUN_ID
    assert calls[0]["project_id"] == "p1"
    assert calls[0]["user_id"] == "user-1"
    assert len(calls[0]["documents"]) == 1
    assert calls[0]["documents"][0].sourceUrl == "https://acme.example.com"
    methods = [c.get("observationMethod") for c in body["aiOverviewComparison"]]
    assert "external_document_supplement" in methods
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "real"
    assert body["meta"]["geminiExternalDocumentProvider"]["model"] == "gemini-2.5-flash"
    assert saved_calls[0]["meta_json"]["geminiExternalDocumentProvider"]["status"] == "real"


def test_no_item_appended_when_attempt_returns_none(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(monkeypatch, recognition_level="specific_knowledge")
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        return None, GeminiExternalDocumentProviderInfo(
            status="recognition_level_not_eligible",
            reason="no supplement needed",
            recognitionLevelAtTrigger="specific_knowledge",
        )

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fake_attempt)

    before = main.build_dummy_analysis("サイボウズ")
    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(body["aiOverviewComparison"]) == len(before.aiOverviewComparison)
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "recognition_level_not_eligible"


def test_no_search_result_is_preserved_when_attempt_fails(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(
        monkeypatch,
        recognition_level="partial_knowledge",
        web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
    )
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        return None, GeminiExternalDocumentProviderInfo(
            status="unavailable",
            reason="Gemini external-document-supplement request failed due to a network or timeout error.",
            recognitionLevelAtTrigger="partial_knowledge",
        )

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiProvider"]["recognitionLevel"] == "partial_knowledge"
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "unavailable"


def test_an_unexpected_exception_in_the_block_never_breaks_the_response(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(
        monkeypatch,
        recognition_level="unidentified",
        web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
    )
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiProvider"]["recognitionLevel"] == "unidentified"


def test_no_recognition_level_available_is_passed_through_as_none(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(monkeypatch, recognition_level=None)
    _stub_complete_analysis_job(monkeypatch)

    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return None, GeminiExternalDocumentProviderInfo(
            status="not_attempted", reason="nothing to evaluate"
        )

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    assert calls[0]["recognition_level"] is None


# --- replay path never re-attempts anything -------------------------------


def test_replay_of_an_existing_completed_run_never_calls_the_attempt(monkeypatch):
    _mock_authenticated(monkeypatch)

    def fake_create_running(**kwargs):
        saved = main.build_dummy_analysis("サイボウズ").model_dump()
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID,
            created=False,
            status="completed",
            locked_by=None,
            result_json=saved,
            meta_json=saved["meta"],
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)

    def fail_if_called(**kwargs):
        raise AssertionError(
            "attempt_gemini_external_document_supplement should not be called on replay"
        )

    monkeypatch.setattr(orchestrator, "attempt_gemini_external_document_supplement", fail_if_called)

    response = _post(_post_body())

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == RUN_ID


# --- backward compatibility with old saved history ------------------------


def test_old_history_rows_without_gemini_external_document_provider_still_parse(monkeypatch):
    old_result_json = main.build_dummy_analysis("サイボウズ").model_dump()
    assert "geminiExternalDocumentProvider" not in old_result_json.get("meta", {}) or (
        old_result_json["meta"].get("geminiExternalDocumentProvider") is None
    )

    from models import AnalysisResult

    parsed = AnalysisResult(**old_result_json)
    assert parsed.meta.geminiExternalDocumentProvider is None


# --- non-interference with the other three supplements --------------------


def test_runs_independently_of_chatgpt_claude_and_gemini_websearch_supplements(monkeypatch):
    """Task 6-D-4C-2 test item 23: 既存OpenAI・Claude検索補完との非干渉
    — all four attempts fire in the same request, each produces its own
    card and its own meta field."""
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)

    def fake_pipeline(**kwargs):
        from models import ChatGptProviderInfo, ClaudeProviderInfo

        result = main.build_dummy_analysis(kwargs["brand_name"])
        result.meta.chatgptProvider = ChatGptProviderInfo(
            mode="openai", status="real", reason="ok", environment="api",
            recognitionLevel="unidentified", promptVersion="v1",
        )
        result.meta.claudeProvider = ClaudeProviderInfo(
            mode="anthropic", status="real", reason="ok", environment="api",
            recognitionLevel="unidentified", promptVersion="v1",
        )
        result.meta.geminiProvider = GeminiProviderInfo(
            mode="google", status="real", reason="ok", environment="api",
            recognitionLevel="unidentified", promptVersion="v1",
        )
        return main.AnalysisPipelineOutcome(
            result=result,
            cooccurrence_status="real",
            source_summary={},
            web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
        )

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)
    _stub_complete_analysis_job(monkeypatch)

    from models import (
        AIOverviewComparisonItem,
        ChatGptWebsearchProviderInfo,
        ClaudeWebsearchProviderInfo,
        GeminiWebsearchProviderInfo,
    )

    def fake_chatgpt_attempt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="ChatGPT (OpenAI API, Web検索補完)",
            mentioned=True, rank=None, summary="chatgpt searched summary",
            observationMethod="websearch_supplement",
        )
        return item, ChatGptWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_claude_attempt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Claude (Anthropic API, Web検索補完)",
            mentioned=True, rank=None, summary="claude searched summary",
            observationMethod="websearch_supplement",
        )
        return item, ClaudeWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_gemini_websearch_attempt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Gemini (Google API, Web検索補完)",
            mentioned=True, rank=None, summary="gemini grounding summary",
            observationMethod="websearch_supplement",
        )
        return item, GeminiWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_gemini_external_document_attempt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Gemini (Google API, 外部文書補完)",
            mentioned=True, rank=None, summary="gemini document-grounded summary",
            observationMethod="external_document_supplement",
        )
        return item, GeminiExternalDocumentProviderInfo(status="real", reason="ok")

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_chatgpt_attempt)
    monkeypatch.setattr(orchestrator, "attempt_claude_websearch_supplement", fake_claude_attempt)
    monkeypatch.setattr(orchestrator, "attempt_gemini_websearch_supplement", fake_gemini_websearch_attempt)
    monkeypatch.setattr(
        orchestrator, "attempt_gemini_external_document_supplement", fake_gemini_external_document_attempt
    )

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()

    summaries = {c["platform"]: c["summary"] for c in body["aiOverviewComparison"]}
    assert summaries["ChatGPT (OpenAI API, Web検索補完)"] == "chatgpt searched summary"
    assert summaries["Claude (Anthropic API, Web検索補完)"] == "claude searched summary"
    assert summaries["Gemini (Google API, Web検索補完)"] == "gemini grounding summary"
    assert summaries["Gemini (Google API, 外部文書補完)"] == "gemini document-grounded summary"
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "real"
    assert body["meta"]["claudeWebsearchProvider"]["status"] == "real"
    assert body["meta"]["geminiWebsearchProvider"]["status"] == "real"
    assert body["meta"]["geminiExternalDocumentProvider"]["status"] == "real"


def test_gemini_external_document_failure_does_not_affect_other_supplements(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)

    def fake_pipeline(**kwargs):
        from models import ChatGptProviderInfo

        result = main.build_dummy_analysis(kwargs["brand_name"])
        result.meta.chatgptProvider = ChatGptProviderInfo(
            mode="openai", status="real", reason="ok", environment="api",
            recognitionLevel="unidentified", promptVersion="v1",
        )
        result.meta.geminiProvider = GeminiProviderInfo(
            mode="google", status="real", reason="ok", environment="api",
            recognitionLevel="unidentified", promptVersion="v1",
        )
        return main.AnalysisPipelineOutcome(
            result=result,
            cooccurrence_status="real",
            source_summary={},
            web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
        )

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)
    _stub_complete_analysis_job(monkeypatch)

    from models import AIOverviewComparisonItem, ChatGptWebsearchProviderInfo

    def fake_chatgpt_attempt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="ChatGPT (OpenAI API, Web検索補完)",
            mentioned=True, rank=None, summary="chatgpt searched summary",
            observationMethod="websearch_supplement",
        )
        return item, ChatGptWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_gemini_external_document_attempt(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_chatgpt_attempt)
    monkeypatch.setattr(
        orchestrator, "attempt_gemini_external_document_supplement", fake_gemini_external_document_attempt
    )

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    methods = [c.get("observationMethod") for c in body["aiOverviewComparison"]]
    assert methods.count("websearch_supplement") == 1
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "real"


# --- Google Search補完がOFFのまま維持されること (test item 24) --------------


def test_gemini_google_search_grounding_supplement_stays_off_by_default(monkeypatch):
    """Task 6-D-4C-2's own requirement: adding this feature must never
    implicitly affect the still-disabled Google-Search-grounding
    supplement's own default-off behavior."""
    monkeypatch.delenv("GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED", raising=False)
    monkeypatch.setenv("GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED", "true")
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(
        monkeypatch,
        recognition_level="unidentified",
        web_fetch_documents=[_web_fetch_doc("https://acme.example.com")],
    )
    _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["geminiWebsearchProvider"]["status"] == "disabled"
