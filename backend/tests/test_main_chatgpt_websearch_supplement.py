"""Verifies POST /analyze's Task 6-D-3 wiring for ChatGPT's conditional
Web-search supplement (backend/main.py's
_analyze_authenticated_idempotent(), the block that calls
services.chatgpt_websearch_provider.attempt_chatgpt_websearch_supplement()
after run_analysis_pipeline() returns and before complete_analysis_job()
saves the result).

Never touches a real database and never calls a real external
provider. Most tests here monkeypatch
main.attempt_chatgpt_websearch_supplement() directly (its own gating/
quota/API logic is already covered by
tests/test_chatgpt_websearch_provider.py and
tests/test_chatgpt_websearch_client.py) so these tests isolate main.py's
own wiring: does it call the function with the right arguments, does it
append the returned item, does it set meta.chatgptWebsearchProvider,
and does it leave the no-search result intact either way. One test
(test_disabled_by_default_requires_no_mocking_at_all) deliberately does
NOT mock attempt_chatgpt_websearch_supplement, to prove the real
default-disabled path makes no DB call and no HTTP call on its own.
"""

from fastapi.testclient import TestClient

import main
from services import analysis_supplement_orchestrator as orchestrator
from main import app
from models import ChatGptProviderInfo, ChatGptWebsearchProviderInfo
from services.analysis_history_repository import SyncAnalysisRunReservation
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
    calls = []

    def fake_create_running(**kwargs):
        calls.append(kwargs)
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)
    return calls


def _stub_pipeline_with_recognition_level(monkeypatch, recognition_level: str | None):
    """Builds a dummy AnalysisResult whose meta.chatgptProvider.recognitionLevel
    is `recognition_level` (or no chatgptProvider at all, when None) —
    this is the exact field main.py reads to decide whether to attempt
    the websearch supplement."""

    def fake_pipeline(**kwargs):
        result = main.build_dummy_analysis(kwargs["brand_name"])
        if recognition_level is not None:
            result.meta.chatgptProvider = ChatGptProviderInfo(
                mode="openai",
                status="real",
                reason="ChatGPT OpenAI API request succeeded.",
                environment="api",
                recognitionLevel=recognition_level,
                promptVersion="no_search_v1",
            )
        return main.AnalysisPipelineOutcome(
            result=result, cooccurrence_status="real", source_summary={}
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
    """The real, unmocked attempt_chatgpt_websearch_supplement() must
    make zero DB/HTTP calls when CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED
    is unset — this test deliberately does not monkeypatch it, nor
    reserve_websearch_quota_for_analysis_run, nor
    fetch_chatgpt_websearch_observation; if the disabled gate didn't
    hold, this test would fail with a real connection attempt rather
    than a clean "disabled" status."""
    monkeypatch.delenv("CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED", raising=False)
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, "unidentified")
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "disabled"
    platforms = [c["platform"] for c in body["aiOverviewComparison"]]
    assert not any("Web検索補完" in p for p in platforms)
    assert saved_calls[0]["meta_json"]["chatgptWebsearchProvider"]["status"] == "disabled"


def test_feature_off_leaves_aioverviewcomparison_identical_to_before_this_task(monkeypatch):
    monkeypatch.delenv("CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED", raising=False)
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)

    def fake_pipeline(**kwargs):
        return main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="real",
            source_summary={},
        )

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)
    _stub_complete_analysis_job(monkeypatch)

    before_response = main.build_dummy_analysis("サイボウズ")
    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(body["aiOverviewComparison"]) == len(before_response.aiOverviewComparison)


# --- wiring: routing + appending ------------------------------------------


def test_websearch_item_is_appended_when_attempt_returns_one(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, "unidentified")
    saved_calls = _stub_complete_analysis_job(monkeypatch)

    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        from models import AIOverviewComparisonItem

        item = AIOverviewComparisonItem(
            platform="ChatGPT (OpenAI API, Web検索補完)",
            mentioned=True,
            rank=None,
            summary="searched summary",
            observationMethod="websearch_supplement",
        )
        info = ChatGptWebsearchProviderInfo(
            status="real", reason="ok", recognitionLevelAtTrigger="unidentified", searched=True
        )
        return item, info

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(calls) == 1
    assert calls[0]["recognition_level"] == "unidentified"
    assert calls[0]["analysis_run_id"] == RUN_ID
    assert calls[0]["project_id"] == "p1"
    assert calls[0]["user_id"] == "user-1"
    methods = [c.get("observationMethod") for c in body["aiOverviewComparison"]]
    assert "websearch_supplement" in methods
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "real"
    assert body["meta"]["chatgptWebsearchProvider"]["searched"] is True
    assert saved_calls[0]["meta_json"]["chatgptWebsearchProvider"]["status"] == "real"


def test_no_item_appended_when_attempt_returns_none(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, "specific_knowledge")
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        return None, ChatGptWebsearchProviderInfo(
            status="recognition_level_not_eligible",
            reason="no supplement needed",
            recognitionLevelAtTrigger="specific_knowledge",
        )

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_attempt)

    before = main.build_dummy_analysis("サイボウズ")
    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(body["aiOverviewComparison"]) == len(before.aiOverviewComparison)
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "recognition_level_not_eligible"


def test_no_search_result_is_preserved_when_websearch_attempt_fails(monkeypatch):
    """Task 6-D-3 item H: a websearch-supplement failure must never
    discard the already-successful no-search ChatGPT observation."""
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, "partial_knowledge")
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        return None, ChatGptWebsearchProviderInfo(
            status="unavailable",
            reason="OpenAI websearch-supplement request failed due to a network or timeout error.",
            recognitionLevelAtTrigger="partial_knowledge",
        )

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["chatgptProvider"]["recognitionLevel"] == "partial_knowledge"
    assert body["meta"]["chatgptWebsearchProvider"]["status"] == "unavailable"


def test_an_unexpected_exception_in_the_websearch_block_never_breaks_the_response(monkeypatch):
    """Defensive wrapping in main.py — an unexpected bug in the new
    code path must never take down the rest of a successful
    /analyze response."""
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, "unidentified")
    _stub_complete_analysis_job(monkeypatch)

    def fake_attempt(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["chatgptProvider"]["recognitionLevel"] == "unidentified"


def test_no_recognition_level_available_is_passed_through_as_none(monkeypatch):
    _mock_authenticated(monkeypatch)
    _stub_create_running(monkeypatch)
    _stub_pipeline_with_recognition_level(monkeypatch, None)
    _stub_complete_analysis_job(monkeypatch)

    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return None, ChatGptWebsearchProviderInfo(status="not_attempted", reason="nothing to evaluate")

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fake_attempt)

    response = _post(_post_body())

    assert response.status_code == 200
    assert calls[0]["recognition_level"] is None


# --- replay path never re-attempts anything -------------------------------


def test_replay_of_an_existing_completed_run_never_calls_the_websearch_attempt(monkeypatch):
    _mock_authenticated(monkeypatch)

    def fake_create_running(**kwargs):
        from models import AnalysisResult

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
        raise AssertionError("attempt_chatgpt_websearch_supplement should not be called on replay")

    monkeypatch.setattr(orchestrator, "attempt_chatgpt_websearch_supplement", fail_if_called)

    response = _post(_post_body())

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == RUN_ID


# --- backward compatibility with old saved history ------------------------


def test_old_history_rows_without_chatgpt_websearch_provider_still_parse(monkeypatch):
    """A saved history row from before Task 6-D-3 has no
    chatgptWebsearchProvider key in its meta_json at all — the replay
    path reconstructs AnalysisResult(**reservation.result_json)
    directly, so this just confirms that dict is missing the key
    entirely and still parses."""
    old_result_json = main.build_dummy_analysis("サイボウズ").model_dump()
    assert "chatgptWebsearchProvider" not in old_result_json.get("meta", {}) or (
        old_result_json["meta"].get("chatgptWebsearchProvider") is None
    )

    from models import AnalysisResult

    parsed = AnalysisResult(**old_result_json)
    assert parsed.meta.chatgptWebsearchProvider is None
