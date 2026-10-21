"""Verifies POST /analyze's Task 6-B4 usage-quota behavior (backend/
main.py's _resolve_required_usage_counters()/_analyze_authenticated_idempotent(),
on top of services.analysis_history_repository.create_running_analysis_run()'s
required_counters mechanism, mocked here — its own query logic is
covered by tests/test_sync_analysis_idempotency_repository.py, and
real-DB concurrency by
tests/test_sync_analysis_idempotency_integration.py).

Never touches a real database and never calls a real external
provider (main.run_analysis_pipeline/main.create_running_analysis_run/
main.complete_analysis_job are monkeypatched in every test that
reaches past the reservation step; where a provider's *resolved mode*
matters, real env vars are set and the real resolve_*_mode()/
resolve_dataforseo_environment() functions run — no network call is
possible from any of them).
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import (
    AnalysisQuotaExceededError,
    SyncAnalysisRunReservation,
    UsageCounterRequirement,
)
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

RUN_ID = "11111111-1111-1111-1111-111111111111"
_DATAFORSEO_ENV_NAMES = [
    "AI_OVERVIEW_PROVIDER_MODE",
    "ALLOW_AI_OVERVIEW_MODE_OVERRIDE",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "DATAFORSEO_API_ENV",
    "DATAFORSEO_LIVE_API_ENABLED",
    "DATAFORSEO_LIVE_CONFIRM_TEXT",
    "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE",
    "CHATGPT_PROVIDER_MODE",
    "ALLOW_CHATGPT_MODE_OVERRIDE",
    "CLAUDE_PROVIDER_MODE",
    "ALLOW_CLAUDE_MODE_OVERRIDE",
    "GEMINI_PROVIDER_MODE",
    "ALLOW_GEMINI_MODE_OVERRIDE",
]


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_authenticated(monkeypatch, *, user_id: str = "user-1", enforce_quota: bool = True):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    if enforce_quota:
        monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    else:
        monkeypatch.delenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", raising=False)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, project_id: True)


def _clear_provider_env(monkeypatch):
    for name in _DATAFORSEO_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name in [
        "ANALYZE_QUOTA_MAX_USER_DAILY",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_SANDBOX",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_SANDBOX",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_LIVE",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_LIVE",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_OPENAI",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_ANTHROPIC",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_ANTHROPIC",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_GOOGLE",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_GOOGLE",
        "ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA",
    ]:
        monkeypatch.delenv(name, raising=False)


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


def _stub_pipeline_success(monkeypatch):
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="real",
            source_summary={},
        ),
    )
    monkeypatch.setattr(main, "complete_analysis_job", lambda run_id, **kwargs: True)


# --- AUTH/QUOTA flag combinations ---------------------------------------


def test_auth_off_quota_on_is_inert_anonymous_flow_unchanged(monkeypatch):
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    _clear_provider_env(monkeypatch)
    pipeline_calls = []
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: (
            pipeline_calls.append(kwargs)
            or main.AnalysisPipelineOutcome(
                result=main.build_dummy_analysis(kwargs["brand_name"]),
                cooccurrence_status="unavailable",
                source_summary={},
            )
        ),
    )
    monkeypatch.setattr(main, "save_analysis_history", lambda **kwargs: None)
    reservation_calls = []
    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: reservation_calls.append(kwargs),
    )

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    assert len(pipeline_calls) == 1
    assert reservation_calls == []


def test_auth_on_quota_off_is_refused_by_default(monkeypatch):
    _clear_provider_env(monkeypatch)
    _mock_authenticated(monkeypatch, enforce_quota=False)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 503
    assert response.json()["code"] == "quota_enforcement_required"


def test_auth_on_quota_off_proceeds_unmetered_with_explicit_dev_override(monkeypatch):
    _clear_provider_env(monkeypatch)
    _mock_authenticated(monkeypatch, enforce_quota=False)
    monkeypatch.setenv("ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA", "true")
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    assert reservation_calls[0]["required_counters"] == []


def test_auth_on_quota_on_is_normal_operation(monkeypatch):
    _clear_provider_env(monkeypatch)
    _mock_authenticated(monkeypatch, enforce_quota=True)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert len(counters) == 3  # user-daily, project-daily, project-monthly, mock mode
    assert {c.metric for c in counters} == {"all_analyses"}


# --- mock/off vs paid-provider counter selection ------------------------


def test_mock_mode_only_consumes_all_analyses_counters(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert all(c.metric == "all_analyses" for c in counters)
    assert len(counters) == 3


def test_dataforseo_sandbox_mode_consumes_sandbox_metric_only(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo_sandbox")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "secret")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    metrics = {c.metric for c in counters}
    assert "dataforseo_sandbox" in metrics
    assert "dataforseo_live" not in metrics
    assert len([c for c in counters if c.metric == "dataforseo_sandbox"]) == 2  # daily + monthly


def test_dataforseo_live_mode_without_gates_consumes_no_dataforseo_metric(monkeypatch):
    """"dataforseo_live" with the Live gate unmet never calls Live (and
    never falls back to Sandbox) — so no dataforseo_* counter should
    be reserved at all, matching resolve_dataforseo_environment()'s
    own None return."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo_live")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "secret")
    # Live gates deliberately left unmet.
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert not any(c.metric.startswith("dataforseo") for c in counters)


def test_dataforseo_live_mode_with_all_gates_consumes_live_metric(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo_live")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "secret")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "ALLOW_DATAFORSEO_LIVE_ONCE")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    metrics = {c.metric for c in counters}
    assert "dataforseo_live" in metrics
    assert "dataforseo_sandbox" not in metrics


def test_chatgpt_mode_off_by_default_consumes_no_openai_metric(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert not any(c.metric == "openai" for c in counters)


def test_chatgpt_mode_openai_consumes_openai_metric(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "openai")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert any(c.metric == "openai" for c in counters)


def test_ai_overview_mock_mode_skips_chatgpt_metric_even_when_chatgpt_mode_is_openai(monkeypatch):
    """Mirrors run_analysis_pipeline()'s own exact rule: ChatGPT is
    never resolved/called at all when aiOverviewMode resolves to
    "mock" — so its quota metric must never be consumed either, even
    if CHATGPT_PROVIDER_MODE itself says "openai"."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "openai")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert not any(c.metric == "openai" for c in counters)


def test_claude_mode_anthropic_consumes_anthropic_metric_even_in_mock_ai_overview(monkeypatch):
    """Unlike chatgptMode, claudeMode is NOT skipped when aiOverviewMode
    is "mock" (see services/claude_provider.py's own docstring) — the
    quota metric selection must mirror that exactly."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "anthropic")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert any(c.metric == "anthropic" for c in counters)


def test_gemini_mode_google_consumes_google_metric(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "google")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert any(c.metric == "google" for c in counters)


def test_websearch_metrics_are_never_reserved_by_a_normal_analysis(monkeypatch):
    """Task 6-D-2A: openai_websearch/anthropic_websearch/google_websearch
    exist only as quota configuration for a *future* conditional
    Web-search follow-up — no code path in this task reserves them, so
    a normal (no-search) analysis must never include them in
    required_counters, even with every provider turned on. This is the
    guard against the exact failure mode item "6" warns about: a 0
    default for an unreserved metric silently turning every normal
    analysis into a 429."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "anthropic")
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "google")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    websearch_metrics = {"openai_websearch", "anthropic_websearch", "google_websearch"}
    assert not any(c.metric in websearch_metrics for c in counters)


def test_allow_mode_override_false_ignores_request_override_for_quota_too(monkeypatch):
    """ALLOW_CHATGPT_MODE_OVERRIDE unset/false means the per-request
    chatgptMode is ignored by resolve_chatgpt_mode() — and therefore
    must also be ignored for quota purposes, since
    _resolve_required_usage_counters() uses the exact same resolved
    value the pipeline will use."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    # ALLOW_CHATGPT_MODE_OVERRIDE left unset (false) — the request body
    # below asks for "openai" anyway.
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post(
        {
            "brandName": "サイボウズ",
            "projectId": "p1",
            "requestId": "req-1",
            "chatgptMode": "openai",
        }
    )

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert not any(c.metric == "openai" for c in counters)


def test_allow_mode_override_true_honors_request_override_for_quota_too(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post(
        {
            "brandName": "サイボウズ",
            "projectId": "p1",
            "requestId": "req-1",
            "chatgptMode": "openai",
        }
    )

    assert response.status_code == 200
    counters = reservation_calls[0]["required_counters"]
    assert any(c.metric == "openai" for c in counters)


def test_quota_limit_values_are_forwarded_from_settings(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_USER_DAILY", "7")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_DAILY", "8")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_MONTHLY", "9")
    _mock_authenticated(monkeypatch)
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    counters = {(c.scope_type, c.period_type): c.limit for c in reservation_calls[0]["required_counters"]}
    assert counters[("user", "daily")] == 7
    assert counters[("project", "daily")] == 8
    assert counters[("project", "monthly")] == 9


# --- 429 quota-exceeded response -----------------------------------------


def test_quota_exceeded_returns_429_with_scope_metric_period_and_available_at(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    _mock_authenticated(monkeypatch)
    pipeline_calls = []
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: pipeline_calls.append(kwargs),
    )

    def fake_create_running(**kwargs):
        raise AnalysisQuotaExceededError(
            scope_type="project",
            scope_id="p1",
            metric="all_analyses",
            period_type="daily",
            period_start=datetime(2026, 3, 5, tzinfo=timezone.utc),
            limit=50,
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "analysis_quota_exceeded"
    assert body["quota"]["scope"] == "project"
    assert body["quota"]["metric"] == "all_analyses"
    assert body["quota"]["period"] == "daily"
    assert body["quota"]["availableAt"] == "2026-03-06T00:00:00+00:00"
    assert pipeline_calls == []


def test_quota_exceeded_monthly_available_at_rolls_over_to_next_month(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    _mock_authenticated(monkeypatch)

    def fake_create_running(**kwargs):
        raise AnalysisQuotaExceededError(
            scope_type="project",
            scope_id="p1",
            metric="all_analyses",
            period_type="monthly",
            period_start=datetime(2026, 12, 1, tzinfo=timezone.utc),
            limit=500,
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 429
    assert response.json()["quota"]["availableAt"] == "2027-01-01T00:00:00+00:00"


def test_quota_exceeded_never_calls_the_pipeline(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    _mock_authenticated(monkeypatch)
    pipeline_calls = []
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    def fake_create_running(**kwargs):
        raise AnalysisQuotaExceededError(
            scope_type="user",
            scope_id="user-1",
            metric="all_analyses",
            period_type="daily",
            period_start=datetime(2026, 3, 5, tzinfo=timezone.utc),
            limit=20,
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 429
    assert pipeline_calls == []


def test_quota_not_exceeded_when_enforcement_disabled_even_with_tiny_limits(monkeypatch):
    """With enforcement disabled, required_counters is always [] —
    tiny/zero env limits configured for later use have no effect at
    all while disabled."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_USER_DAILY", "0")
    _mock_authenticated(monkeypatch, enforce_quota=False)
    monkeypatch.setenv("ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA", "true")
    reservation_calls = _stub_create_running(monkeypatch)
    _stub_pipeline_success(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    assert reservation_calls[0]["required_counters"] == []


# --- anonymous-mode regression ------------------------------------------


def test_anonymous_mode_never_builds_required_counters_even_with_quota_enforcement_on(monkeypatch):
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        ),
    )
    monkeypatch.setattr(main, "save_analysis_history", lambda **kwargs: None)
    reservation_calls = []
    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: reservation_calls.append(kwargs),
    )

    response = client.post("/analyze", json={"brandName": "サイボウズ", "requestId": "req-1"})

    assert response.status_code == 200
    assert reservation_calls == []
