"""Verifies POST /analysis-runs/{id}/web-ai-gap/ai-comparison (see
main.py's generate_web_ai_gap_ai_comparison(),
services.ai_gap_comparison.generate_ai_gap_comparison()) — added so a
依頼者 can generate an AI-powered Web/AI gap comparison on demand from
the history detail screen.

Authorization was tightened by fix/history-read-token-write-isolation
(pre-demo audit issue B2): this endpoint is now JWT-only, with no
HISTORY_READ_TOKEN fallback of any kind — mirrors
tests/test_main_tags_categories_api.py's auth-test conventions exactly.
Every content/behavior test below authenticates via JWT
(_mock_jwt_dependencies + _jwt_headers()) rather than the old
HISTORY_READ_TOKEN-only path, since that path is no longer valid for
this endpoint at all.

Never touches a real database (main.repository_get_analysis_run/
repository_update_analysis_result are monkeypatched) and never calls
the real Anthropic API (main.generate_ai_gap_comparison is
monkeypatched) — JWT/project-access behavior is already covered by
tests/test_jwt_auth.py and tests/test_analysis_history_repository.py,
and the comparison-call logic itself by tests/test_ai_gap_comparison.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from models import AiGapActionRecommendation, WebAiGapAiComparison
from services.ai_gap_comparison import AiGapComparisonOutcome
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
RUN_ID = "11111111-1111-1111-1111-111111111111"

AI_COMPARISON_PATH = f"/analysis-runs/{RUN_ID}/web-ai-gap/ai-comparison"


def _enable_read_env(monkeypatch, token: str = TEST_TOKEN):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("HISTORY_READ_TOKEN", token)


def _auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    return {HISTORY_READ_TOKEN_HEADER: token}


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_jwt_dependencies(monkeypatch, *, user_id: str = "user-1", can_access_run: bool = True):
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(
        main, "can_user_access_analysis_run", lambda conn, uid, run_id: can_access_run
    )


def _fake_detail(**result_overrides) -> dict:
    result = {
        "webAiGap": {
            "status": "real",
            "webContext": {"summary": "Web excerpt", "sourceType": "web_fetch", "sourceUrl": None},
            "aiContexts": [{"platform": "chatgpt", "summary": "AI excerpt", "status": "real"}],
            "gapSummary": "x",
            "suggestions": [],
            "note": "note",
        },
    }
    result.update(result_overrides)
    return {
        "id": RUN_ID,
        "brand": {"id": "brand-1", "name": "Acme", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "Acme"},
            "sourceSummary": None,
            "startedAt": "2026-10-01T00:00:00+00:00",
            "completedAt": "2026-10-01T00:00:10+00:00",
        },
        "result": result,
        "meta": {},
        "projectId": "project-1",
    }


def _comparison(**overrides) -> WebAiGapAiComparison:
    fields = {
        "matchedPoints": ["matched"],
        "webStrongAiWeak": ["web strong"],
        "aiStrongWebWeak": ["ai strong"],
        "gapSummary": "gap",
        "recommendations": ["recommend"],
        "caution": "AIによる比較であり、AIの内部認識を直接示すものではありません。",
    }
    fields.update(overrides)
    return WebAiGapAiComparison(**fields)


def _mock_successful_generation(monkeypatch, *, comparison: WebAiGapAiComparison | None = None):
    result = comparison or _comparison()
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: AiGapComparisonOutcome(success=True, reason="ok", comparison=result),
    )
    return result


def _mock_failed_generation(
    monkeypatch, *, reason: str = "boom", unavailable: bool = False, internal_reason: str | None = None
):
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: AiGapComparisonOutcome(
            success=False, reason=reason, unavailable=unavailable, internal_reason=internal_reason
        ),
    )


# --- disabled / unconfigured -------------------------------------------


def test_ai_comparison_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 503


def test_ai_comparison_rejected_when_jwt_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503


# --- HISTORY_READ_TOKEN is no longer a valid credential for this
# endpoint (fix/history-read-token-write-isolation) --------------------


def test_ai_comparison_rejected_with_history_read_token_alone(monkeypatch):
    """A correct HISTORY_READ_TOKEN, with no Authorization header at
    all, must never be enough to trigger an AI-gap comparison
    generation (and therefore never consume the Anthropic API budget
    on behalf of an unauthenticated caller) — previously this succeeded
    unconditionally (pre-demo audit issue B2)."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    generate_calls = []
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: generate_calls.append(kwargs),
    )

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 401
    assert generate_calls == []


def test_ai_comparison_rejected_with_no_credentials_at_all(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.post(AI_COMPARISON_PATH)

    assert response.status_code == 401


def test_ai_comparison_token_value_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers={**_jwt_headers(), **_auth_headers()})

    assert TEST_TOKEN not in response.text


# --- JWT-authenticated: content/behavior (access-checked by run id
# before anything else, verified separately further below) -----------


def test_ai_comparison_jwt_mode_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    comparison = _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["analysisRunId"] == RUN_ID
    assert body["webAiGapAiComparison"]["matchedPoints"] == comparison.matchedPoints
    assert body["webAiGapAiComparison"]["method"] == "ai_comparison"


def test_ai_comparison_text_fallback_is_saved_and_returned_and_preserves_web_ai_gap(monkeypatch):
    """fix/ai-gap-comparison-text-fallback: a text-fallback comparison
    (method="ai_comparison_text_fallback", textSummary set) is persisted
    and returned exactly like a normal structured one, and the existing
    rule-based webAiGap is still left untouched."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    fallback_comparison = _comparison(
        method="ai_comparison_text_fallback",
        matchedPoints=[],
        webStrongAiWeak=[],
        aiStrongWebWeak=[],
        gapSummary="Claudeが構造化JSONではなく文章形式で比較結果を返しました。",
        recommendations=["上記の文章形式の比較結果を確認してください。"],
        textSummary="Web上では...と説明されていますが、AI回答では...",
    )
    _mock_successful_generation(monkeypatch, comparison=fallback_comparison)
    saved = {}

    def fake_update(run_id, *, result_json, meta_json):
        saved["result_json"] = result_json
        return True

    monkeypatch.setattr(main, "repository_update_analysis_result", fake_update)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["webAiGapAiComparison"]["method"] == "ai_comparison_text_fallback"
    assert body["webAiGapAiComparison"]["textSummary"] == fallback_comparison.textSummary
    assert saved["result_json"]["webAiGapAiComparison"]["method"] == "ai_comparison_text_fallback"
    assert saved["result_json"]["webAiGap"] == detail["result"]["webAiGap"]


def test_ai_comparison_json_like_fallback_is_saved_and_returned_and_preserves_web_ai_gap(
    monkeypatch,
):
    """fix/ai-gap-comparison-json-like-fallback-display: a json-like-
    fallback comparison (method="ai_comparison_json_like_fallback",
    structured list fields populated, textSummary unset) is persisted
    and returned exactly like a normal structured one, and the existing
    rule-based webAiGap is still left untouched."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    json_like_comparison = _comparison(
        method="ai_comparison_json_like_fallback",
        matchedPoints=["一致点A"],
        webStrongAiWeak=["Web強みA"],
        aiStrongWebWeak=["AI強みA"],
        gapSummary="ズレの要約です。",
        recommendations=[],
        textSummary=None,
    )
    _mock_successful_generation(monkeypatch, comparison=json_like_comparison)
    saved = {}

    def fake_update(run_id, *, result_json, meta_json):
        saved["result_json"] = result_json
        return True

    monkeypatch.setattr(main, "repository_update_analysis_result", fake_update)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["webAiGapAiComparison"]["method"] == "ai_comparison_json_like_fallback"
    assert body["webAiGapAiComparison"]["matchedPoints"] == ["一致点A"]
    assert body["webAiGapAiComparison"]["textSummary"] is None
    assert saved["result_json"]["webAiGapAiComparison"]["method"] == "ai_comparison_json_like_fallback"
    assert saved["result_json"]["webAiGap"] == detail["result"]["webAiGap"]


def test_ai_comparison_action_recommendations_are_saved_and_returned(monkeypatch):
    """feature/ai-gap-action-recommendations: actionRecommendations
    persist and round-trip through the API exactly like the rest of
    webAiGapAiComparison, and the existing rule-based webAiGap stays
    untouched."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    comparison_with_actions = _comparison(
        actionRecommendations=[
            AiGapActionRecommendation(
                title="SEO対策の実績を会社概要に明記する",
                issue="AI回答では一般的なブランディング会社として説明される",
                action="会社概要ページにSEO対策の実績を追記する",
                target="会社概要ページ(候補)",
                evidence="Web上ではSEO対策が中心だが、AI回答ではブランディングのみ言及",
                priority="high",
                verification="追記後、同じ質問でAI観測を再実行し説明内容を確認する",
            )
        ],
    )
    _mock_successful_generation(monkeypatch, comparison=comparison_with_actions)
    saved = {}

    def fake_update(run_id, *, result_json, meta_json):
        saved["result_json"] = result_json
        return True

    monkeypatch.setattr(main, "repository_update_analysis_result", fake_update)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    body = response.json()
    action_recommendations = body["webAiGapAiComparison"]["actionRecommendations"]
    assert len(action_recommendations) == 1
    assert action_recommendations[0]["priority"] == "high"
    assert action_recommendations[0]["verification"] == "追記後、同じ質問でAI観測を再実行し説明内容を確認する"
    assert (
        saved["result_json"]["webAiGapAiComparison"]["actionRecommendations"][0]["title"]
        == "SEO対策の実績を会社概要に明記する"
    )
    assert saved["result_json"]["webAiGap"] == detail["result"]["webAiGap"]


def test_ai_comparison_action_recommendation_with_null_target_round_trips(monkeypatch):
    """fix/ai-gap-action-recommendations-missing: target(省略可能)が
    Noneの項目でも、フィールド自体は失われずnullとしてAPI応答・保存先の
    両方に残ること。"""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    comparison_with_actions = _comparison(
        actionRecommendations=[
            AiGapActionRecommendation(
                title="SEO対策の実績を追記する",
                issue="一般的なブランディング会社として説明される",
                action="関連ページに実績を追記する",
                evidence="Web上ではSEO対策が中心だが、AI回答では言及がない",
            )
        ],
    )
    _mock_successful_generation(monkeypatch, comparison=comparison_with_actions)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    action_recommendations = response.json()["webAiGapAiComparison"]["actionRecommendations"]
    assert action_recommendations[0]["target"] is None
    assert action_recommendations[0]["priority"] == "medium"
    assert "AI観測を行い" in action_recommendations[0]["verification"]


def test_ai_comparison_action_recommendations_absent_when_not_set(monkeypatch):
    """actionRecommendationsを指定しない通常の比較結果は、応答・保存先
    いずれもnullのまま——既存の互換性を壊さない。"""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json()["webAiGapAiComparison"]["actionRecommendations"] is None


def test_ai_comparison_jwt_mode_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: None)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 404


def test_ai_comparison_passes_through_brand_name_and_result_json(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    received_kwargs = {}

    def fake_generate(**kwargs):
        received_kwargs.update(kwargs)
        return AiGapComparisonOutcome(success=True, reason="ok", comparison=_comparison())

    monkeypatch.setattr(main, "generate_ai_gap_comparison", fake_generate)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert received_kwargs["brand_name"] == "Acme"
    assert received_kwargs["result_json"] == detail["result"]


def test_ai_comparison_saves_only_webAiGapAiComparison_and_does_not_overwrite_webAiGap(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    _mock_successful_generation(monkeypatch)
    saved = {}

    def fake_update(run_id, *, result_json, meta_json):
        saved["result_json"] = result_json
        saved["meta_json"] = meta_json
        return True

    monkeypatch.setattr(main, "repository_update_analysis_result", fake_update)

    client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert saved["result_json"]["webAiGap"] == detail["result"]["webAiGap"]
    assert "webAiGapAiComparison" in saved["result_json"]
    assert saved["meta_json"] == detail["meta"]


def test_ai_comparison_failure_not_attempted_returns_503_and_does_not_write_to_db(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(
        monkeypatch,
        reason="Anthropic API key is not configured.",
        unavailable=True,
        internal_reason="credentials_missing",
    )
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_update_analysis_result",
        lambda run_id, **kw: update_calls.append(run_id) or True,
    )

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503
    assert response.json() == {
        "error": "Anthropic API key is not configured.",
        "reason": "credentials_missing",
    }
    assert update_calls == []


def test_ai_comparison_failure_attempted_returns_502_and_does_not_write_to_db(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(
        monkeypatch,
        reason="Anthropic API request failed with HTTP 500.",
        unavailable=False,
        internal_reason="non_200_status",
    )
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_update_analysis_result",
        lambda run_id, **kw: update_calls.append(run_id) or True,
    )

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 502
    assert response.json() == {
        "error": "Anthropic API request failed with HTTP 500.",
        "reason": "non_200_status",
    }
    assert update_calls == []


def test_ai_comparison_failure_response_reason_is_none_when_not_set(monkeypatch):
    """A failure outcome that doesn't set internal_reason (e.g. a
    future/unexpected failure path) still returns a well-formed body
    with reason: null, rather than omitting the key or erroring."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(monkeypatch, reason="boom", unavailable=False, internal_reason=None)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 502
    assert response.json() == {"error": "boom", "reason": None}


def test_ai_comparison_failure_response_never_includes_raw_model_output_or_secrets(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(
        monkeypatch,
        reason="AI比較の生成結果を読み取れませんでした。時間をおいて再度お試しください。",
        unavailable=False,
        internal_reason="json_decode_failed",
    )

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())
    text = response.text

    assert "sk-ant-" not in text
    assert "CLAUDE_API_KEY" not in text


def test_ai_comparison_returns_503_when_repository_update_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)

    def raising_update(run_id, **kw):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_update_analysis_result", raising_update)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503


def test_ai_comparison_returns_404_when_update_reports_run_vanished(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: False)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 404


def test_ai_comparison_returns_503_when_get_analysis_run_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)

    def raising_get(run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503


# --- JWT-authenticated: access control itself -------------------------


def test_ai_comparison_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling the Anthropic API or touching the DB — this is
    what keeps a user who can't see a run (e.g. a different project)
    from triggering a billable call for it."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    generate_calls = []
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: generate_calls.append(kwargs)
        or AiGapComparisonOutcome(success=True, reason="ok", comparison=_comparison()),
    )

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 403
    assert generate_calls == []


def test_ai_comparison_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())

    def raising_access_check(conn, uid, run_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_analysis_run", raising_access_check)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503


def test_ai_comparison_rejected_with_invalid_jwt(monkeypatch):
    """A verification failure (expired/bad signature/etc.) must also
    never reach generate_ai_gap_comparison() — no external API call
    happens here either."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    generate_calls = []
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: generate_calls.append(kwargs),
    )

    def raising_verify(token, settings):
        raise JWTAuthError("expired", "token expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raising_verify)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 401
    assert generate_calls == []
