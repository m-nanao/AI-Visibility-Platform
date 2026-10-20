"""Verifies POST /analyze's ANALYZE_AUTH_REQUIRED gate (see main.py's
_resolve_analyze_project_auth(), services/analyze_auth_settings.py) —
added by Task 6-B2 (feature/sync-analyze-jwt-project-auth) so a future
production switch-on can require a verified Supabase JWT + project
access before accepting a sync analysis, while the flag stays false
(the default) today with zero behavior change.

Never touches a real database (main.open_history_db_connection,
main.can_user_access_project are monkeypatched) and never calls a real
external provider (main.run_analysis_pipeline/main.save_analysis_history
are monkeypatched directly in every auth-focused test here) — the
pipeline's own provider-mode logic is already covered elsewhere
(tests/test_ai_overview_provider.py etc.).
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import AnalysisHistorySaveResult
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_jwt_dependencies(monkeypatch, *, user_id: str = "user-1", can_access_project: bool = True):
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(
        main, "can_user_access_project", lambda conn, uid, project_id: can_access_project
    )


def _stub_pipeline_and_save(monkeypatch):
    """Lets analyze() run to completion (200) without touching any real
    provider or DB — used only by tests that need to reach past the
    auth gate to assert what happens afterward."""
    pipeline_calls = []
    save_calls = []

    def fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        return main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        )

    def fake_save(**kwargs):
        save_calls.append(kwargs)
        return AnalysisHistorySaveResult(
            analysis_run_id="11111111-1111-1111-1111-111111111111",
            brand_id="22222222-2222-2222-2222-222222222222",
        )

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)
    monkeypatch.setattr(main, "save_analysis_history", fake_save)
    return pipeline_calls, save_calls


# --- ANALYZE_AUTH_REQUIRED flag resolution ------------------------------


def test_analyze_auth_defaults_to_not_required_when_unset(monkeypatch):
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    from services.analyze_auth_settings import load_analyze_auth_settings

    assert load_analyze_auth_settings().auth_required is False


def test_analyze_auth_required_true_values(monkeypatch):
    from services.analyze_auth_settings import load_analyze_auth_settings

    for value in ("true", "1", "yes", "on", "True", "ON"):
        monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", value)
        assert load_analyze_auth_settings().auth_required is True, value


def test_analyze_auth_required_false_values(monkeypatch):
    from services.analyze_auth_settings import load_analyze_auth_settings

    for value in ("false", "0", "no", "off", "", "garbage"):
        monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", value)
        assert load_analyze_auth_settings().auth_required is False, value


# --- Flag OFF: existing anonymous behavior fully preserved -------------


def test_analyze_flag_off_ignores_jwt_and_project_id_entirely(monkeypatch):
    """Even if a caller sends an Authorization header and a projectId,
    with the flag off neither is consulted at all — proves the legacy
    path never even reaches _verify_jwt_bearer()/can_user_access_project()."""
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    jwt_calls = []
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: jwt_calls.append(token)
    )
    project_calls = []
    monkeypatch.setattr(
        main,
        "can_user_access_project",
        lambda conn, uid, project_id: project_calls.append(project_id),
    )
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "some-project"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 200
    assert jwt_calls == []
    assert project_calls == []
    assert len(pipeline_calls) == 1
    assert len(save_calls) == 1
    # The legacy path never forwards projectId into save_analysis_history().
    assert save_calls[0]["project_id"] is None


def test_analyze_flag_off_anonymous_request_still_works(monkeypatch):
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    assert response.json()["brandName"] == "サイボウズ"
    assert len(pipeline_calls) == 1
    assert save_calls[0]["project_id"] is None


# --- Flag ON: authorization enforced ------------------------------------


def test_analyze_flag_on_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post("/analyze", json={"brandName": "サイボウズ", "projectId": "p1"})

    assert response.status_code == 401
    assert response.json()["code"] == "auth_required"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_rejects_invalid_jwt(monkeypatch):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    def raising_verify(token, settings):
        raise JWTAuthError("expired", "token expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raising_verify)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "p1"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_rejects_when_jwt_verification_not_configured(monkeypatch):
    """A misconfigured server (AUTH_JWT_ENABLED=false or no
    SUPABASE_JWKS_URL) must fail closed with 503 — never silently fall
    back to the anonymous path just because ANALYZE_AUTH_REQUIRED is
    true. Also carries the stable `code: "auth_unavailable"` (Task 7)
    so a caller never has to match this response's exact English
    `error` prose to tell it apart from an unrelated 503."""
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "p1"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "auth_unavailable"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_rejects_missing_project_id(monkeypatch):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    _mock_jwt_dependencies(monkeypatch)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze", json={"brandName": "サイボウズ"}, headers=_jwt_headers()
    )

    assert response.status_code == 400
    assert response.json()["code"] == "project_id_required"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_rejects_blank_project_id(monkeypatch):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    _mock_jwt_dependencies(monkeypatch)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "   "},
        headers=_jwt_headers(),
    )

    assert response.status_code == 400
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_rejects_inaccessible_project(monkeypatch):
    """False from can_user_access_project() must produce 403 without
    ever calling run_analysis_pipeline() or save_analysis_history() —
    a caller who can't access a project must not be able to trigger a
    (possibly billable) analysis "on behalf of" it either."""
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_project=False)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "someone-elses-project"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "project_access_denied"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_returns_503_when_project_access_check_fails(monkeypatch):
    """Also carries `code: "auth_unavailable"` (Task 7) — the same
    stable code as the JWT-not-configured 503 above, since from a
    caller's point of view both mean the same thing: an auth-layer
    problem, not the caller's fault, distinct from an unrelated 503."""
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())

    def raising_access_check(conn, uid, project_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_project", raising_access_check)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "p1"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "auth_unavailable"
    assert pipeline_calls == []
    assert save_calls == []


def test_analyze_flag_on_succeeds_with_valid_jwt_and_accessible_project(monkeypatch):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_project=True)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "my-project"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 200
    assert response.json()["brandName"] == "サイボウズ"
    assert len(pipeline_calls) == 1
    # The verified (not client-trusted-as-is) project id is what
    # actually reaches save_analysis_history().
    assert save_calls[0]["project_id"] == "my-project"


def test_analyze_flag_on_never_trusts_a_project_id_the_caller_cannot_access(monkeypatch):
    """Even though the request body names a specific projectId,
    can_user_access_project() returning False for it must block the
    save — this is the "クライアントが指定したprojectIdを無検証で保存
    しない" requirement verified end-to-end."""
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_project=False)
    pipeline_calls, save_calls = _stub_pipeline_and_save(monkeypatch)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "projectId": "not-mine"},
        headers=_jwt_headers(),
    )

    assert response.status_code == 403
    assert save_calls == []
