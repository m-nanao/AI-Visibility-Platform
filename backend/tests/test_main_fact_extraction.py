"""Verifies POST /analyze's Task 6-D-5C-2 wiring for Claude-based fact
extraction (backend/main.py's _analyze_authenticated_idempotent(), the
block that calls
services.fact_extraction_provider.attempt_fact_extraction() after
run_analysis_pipeline() returns and before complete_analysis_job()
saves the result) — mirrors
tests/test_main_gemini_external_document_supplement.py's structure.

Never touches a real database and never calls a real external
provider.
"""

from fastapi.testclient import TestClient

import main
from main import app
from models import AIOverviewComparisonItem, RawFactClaimCandidate
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.analysis_history_repository import SyncAnalysisRunReservation
from services.fact_extraction_client import FactExtractionClientResult
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

RUN_ID = "11111111-1111-1111-1111-111111111111"


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


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
    def fake_create_running(**kwargs):
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)


def _chatgpt_card(**overrides) -> AIOverviewComparisonItem:
    base = dict(
        platform=CHATGPT_PLATFORM_LABEL,
        mentioned=True,
        rank=1,
        summary="短い要約",
        fullSummary="代表者は山田太郎です。",
        observationMethod=None,
        model="gpt-5",
    )
    base.update(overrides)
    return AIOverviewComparisonItem(**base)


def _stub_pipeline(monkeypatch, *, chatgpt_card: AIOverviewComparisonItem | None):
    def fake_pipeline(**kwargs):
        result = main.build_dummy_analysis(kwargs["brand_name"])
        if chatgpt_card is not None:
            result.aiOverviewComparison = [*result.aiOverviewComparison, chatgpt_card]
        return main.AnalysisPipelineOutcome(result=result, cooccurrence_status="real", source_summary={})

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)


def _stub_complete_analysis_job(monkeypatch):
    saved_calls = []

    def fake_complete(run_id, **kwargs):
        saved_calls.append(kwargs)
        return True

    monkeypatch.setattr(main, "complete_analysis_job", fake_complete)
    return saved_calls


def _post_body(**overrides):
    body = {"brandName": "Acme", "projectId": "p1", "requestId": "req-1"}
    body.update(overrides)
    return body


# --- feature OFF (default) -------------------------------------------------


def test_disabled_by_default_requires_no_mocking_at_all(monkeypatch):
    """The real, unmocked attempt_fact_extraction() must make zero
    DB/HTTP calls when FACT_EXTRACTION_ENABLED is unset."""
    monkeypatch.delenv("FACT_EXTRACTION_ENABLED", raising=False)
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(monkeypatch, chatgpt_card=_chatgpt_card())
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["factExtraction"]["status"] == "disabled"
    assert saved_calls[0]["result_json"]["factExtraction"]["status"] == "disabled"


def test_no_eligible_card_reports_no_eligible_card(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline(monkeypatch, chatgpt_card=None)
    _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    assert response.json()["factExtraction"]["status"] == "no_eligible_card"


# --- real end-to-end attempt (Claude call mocked) ---------------------------


def _mock_claude_call(monkeypatch, client_result: FactExtractionClientResult):
    from services.claude_settings import ClaudeCredentials

    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    import services.fact_extraction_provider as fep

    monkeypatch.setattr(fep, "get_claude_credentials", lambda: ClaudeCredentials(api_key="k"))
    monkeypatch.setattr(fep, "reserve_websearch_quota_for_analysis_run", lambda **kwargs: None)
    monkeypatch.setattr(fep, "fetch_fact_extraction", lambda *args, **kwargs: client_result)


def test_real_extraction_end_to_end_saved_into_result_and_history(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    card = _chatgpt_card(fullSummary="代表者は山田太郎です。")
    _stub_pipeline(monkeypatch, chatgpt_card=card)
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    _mock_claude_call(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["factExtraction"]["status"] == "real"
    assert len(body["factExtraction"]["claims"]) == 1
    assert body["factExtraction"]["claims"][0]["sourceText"] == "山田太郎"
    assert saved_calls[0]["result_json"]["factExtraction"]["status"] == "real"


def test_fabricated_span_from_claude_is_rejected_end_to_end(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    card = _chatgpt_card(fullSummary="代表者は山田太郎です。")
    _stub_pipeline(monkeypatch, chatgpt_card=card)
    _stub_complete_analysis_job(monkeypatch)

    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は鈴木一郎",
        sourceText="鈴木一郎",
        sourceStartIndex=0,
        sourceEndIndex=4,
    )
    _mock_claude_call(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["factExtraction"]["status"] == "partial"
    assert body["factExtraction"]["claims"] == []
    assert body["factExtraction"]["rejectedCount"] == 1


# --- non-interference with existing providers/quota ------------------------


def test_fact_extraction_never_passed_to_other_provider_attempt_functions(monkeypatch):
    """Confirms officialUrl-style non-interference for this feature
    too: none of the other attempt_*_supplement call sites ever
    receive anything fact-extraction-related."""
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    card = _chatgpt_card()
    _stub_pipeline(monkeypatch, chatgpt_card=card)
    _stub_complete_analysis_job(monkeypatch)

    captured = {}

    def _capture(name):
        def _inner(*args, **kwargs):
            captured[name] = kwargs
            return None, type("Info", (), {"status": "not_attempted"})()

        return _inner

    monkeypatch.setattr(main, "attempt_chatgpt_websearch_supplement", _capture("chatgpt"))
    monkeypatch.setattr(main, "attempt_claude_websearch_supplement", _capture("claude"))
    monkeypatch.setattr(main, "attempt_gemini_websearch_supplement", _capture("gemini"))
    monkeypatch.setattr(
        main, "attempt_gemini_external_document_supplement", _capture("gemini_external_document")
    )
    import services.fact_extraction_provider as fep

    monkeypatch.setattr(fep, "get_claude_credentials", lambda: None)

    response = _post(_post_body())

    assert response.status_code == 200
    assert len(captured) == 4
    for kwargs in captured.values():
        assert all("fact" not in key.lower() for key in kwargs)


def test_fact_extraction_consumes_no_other_providers_quota(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    card = _chatgpt_card()
    _stub_pipeline(monkeypatch, chatgpt_card=card)
    _stub_complete_analysis_job(monkeypatch)

    import services.fact_extraction_provider as fep

    monkeypatch.setattr(fep, "get_claude_credentials", lambda: None)

    reserve_calls = []

    def _capture_reserve(**kwargs):
        reserve_calls.append(kwargs)
        raise AssertionError("should not reach reservation without credentials")

    monkeypatch.setattr(fep, "reserve_websearch_quota_for_analysis_run", _capture_reserve)

    response = _post(_post_body())

    assert response.status_code == 200
    assert reserve_calls == []
    assert response.json()["factExtraction"]["status"] == "no_credentials"


# --- redisplaying a saved run never triggers a new extraction call ---------


def test_get_analysis_run_detail_never_calls_attempt_fact_extraction():
    """Task 6-D-5C-2 item 9: 'same run redisplayed never re-calls the
    API'. GET /analysis-runs/{id} only ever reads whatever
    factExtraction was already saved in result_json — it has no code
    path that imports or calls attempt_fact_extraction() at all."""
    import inspect

    source = inspect.getsource(main.get_analysis_run)
    assert "attempt_fact_extraction" not in source
    assert "fact_extraction_provider" not in source


# --- anonymous path never attempts fact extraction at all ------------------


def test_anonymous_analyze_never_sets_fact_extraction(monkeypatch):
    """The anonymous /analyze path (ANALYZE_AUTH_REQUIRED off, today's
    default) has no 'running' reservation to attach quota to and never
    calls attempt_fact_extraction at all — factExtraction must stay
    None, exactly like before this feature existed."""
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")

    import services.fact_extraction_provider as fep

    def _never_call(**kwargs):
        raise AssertionError("attempt_fact_extraction must never be called on the anonymous path")

    monkeypatch.setattr(fep, "reserve_websearch_quota_for_analysis_run", _never_call)
    monkeypatch.setattr(main, "attempt_fact_extraction", _never_call)

    response = client.post("/analyze", json={"brandName": "Acme"})

    assert response.status_code == 200
    assert response.json()["factExtraction"] is None
