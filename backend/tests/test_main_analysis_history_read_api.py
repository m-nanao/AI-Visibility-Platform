"""Verifies GET /analysis-runs, GET /analysis-runs/{id}, and GET
/analysis-runs/{id}/comparison (see main.py,
docs/20_analysis_history_read_api_design.md), including the
HISTORY_READ_TOKEN gate added on top of READ_HISTORY_ENABLED (see
docs/24_auth_rls_history_access_design.md) and the JWT verification +
project-access wiring added on top of that (see
docs/32_backend_jwt_verification_design.md "16"/"17").

These tests never touch a real database — main.repository_list_analysis_runs
/ main.repository_get_analysis_run are monkeypatched at the main module
level (mirrors the existing main.fetch_url_texts / main.save_analysis_history
monkeypatch pattern in tests/test_main.py / tests/test_main_analysis_history.py).
READ_HISTORY_ENABLED/DATABASE_URL/HISTORY_READ_TOKEN env-var-driven skip
behavior itself is covered by tests/test_db_settings.py; list_analysis_runs()/
get_analysis_run()'s own query/error behavior is covered by
tests/test_analysis_history_repository.py. JWT signature/claim
verification itself is covered by tests/test_jwt_auth.py — this file
mocks main.verify_supabase_jwt directly rather than re-deriving RSA/JWKS
material, since its job is to verify main.py's own wiring and
status-code mapping.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER
from main import app
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"


def _clear_read_env(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)


def _enable_read_env(monkeypatch, token: str = TEST_TOKEN):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("HISTORY_READ_TOKEN", token)


def _auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    return {HISTORY_READ_TOKEN_HEADER: token}


# --- disabled / unconfigured → 503 ----------------------------------------


def test_list_returns_503_when_read_history_disabled(monkeypatch):
    _clear_read_env(monkeypatch)

    response = client.get("/analysis-runs")

    assert response.status_code == 503
    assert "error" in response.json()


def test_detail_returns_503_when_read_history_disabled(monkeypatch):
    _clear_read_env(monkeypatch)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 503
    assert "error" in response.json()


def test_list_returns_503_when_database_url_missing(monkeypatch):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/analysis-runs")

    assert response.status_code == 503


def test_db_save_enabled_alone_does_not_enable_read_api(monkeypatch):
    """DB_SAVE_ENABLED=true (with DATABASE_URL set) must not enable the
    read API by itself — READ_HISTORY_ENABLED is a separate flag."""
    monkeypatch.setenv("DB_SAVE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/analysis-runs")

    assert response.status_code == 503


# --- HISTORY_READ_TOKEN gate -----------------------------------------------


def test_list_returns_503_with_distinct_message_when_read_history_disabled(monkeypatch):
    _clear_read_env(monkeypatch)

    response = client.get("/analysis-runs")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read API is not enabled"}


def test_list_returns_503_with_distinct_message_when_database_url_missing(monkeypatch):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/analysis-runs")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read API is not configured"}


def test_list_returns_503_when_history_read_token_not_configured(monkeypatch):
    """READ_HISTORY_ENABLED=true and DATABASE_URL set are not enough —
    an operator must also configure HISTORY_READ_TOKEN."""
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/analysis-runs")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read token is not configured"}


def test_detail_returns_503_when_history_read_token_not_configured(monkeypatch):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read token is not configured"}


def test_list_returns_403_when_token_header_missing(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get("/analysis-runs")

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


def test_list_returns_403_when_token_header_mismatched(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get("/analysis-runs", headers=_auth_headers("wrong-token"))

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


def test_detail_returns_403_when_token_header_missing(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


def test_detail_returns_403_when_token_header_mismatched(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers("wrong-token"),
    )

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


def test_list_token_value_never_appears_in_response_body(monkeypatch):
    """Whichever gate rejects the request, the configured token must
    never leak into the response body."""
    _enable_read_env(monkeypatch)

    response = client.get("/analysis-runs", headers=_auth_headers("wrong-token"))

    assert TEST_TOKEN not in response.text
    assert "wrong-token" not in response.text


# --- repository failure → 503 ----------------------------------------------


def test_list_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_list(**kwargs):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_list_analysis_runs", raising_list)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 503


def test_detail_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_get(analysis_run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers(),
    )

    assert response.status_code == 503


# --- not found → 404 --------------------------------------------------------


def test_detail_returns_404_when_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: None)

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers(),
    )

    assert response.status_code == 404


def test_detail_returns_403_before_404_when_token_missing(monkeypatch):
    """Access control is checked before the repository is even queried
    — an unauthenticated caller must not learn whether an id exists."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: None)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 403


# --- success cases -----------------------------------------------------------


def test_list_success_excludes_result_json(monkeypatch):
    _enable_read_env(monkeypatch)
    fake_items = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brandName": "サイボウズ",
            "canonicalDomain": "cybozu.co.jp",
            "status": "completed",
            "visibilityScore": 86,
            "sourceSummary": {"web_fetch": 1, "common_crawl": 3},
            "startedAt": "2026-09-09T00:00:00+09:00",
            "completedAt": "2026-09-09T00:00:10+09:00",
            "createdAt": "2026-09-09T00:00:10+09:00",
        }
    ]
    calls = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        return fake_items

    monkeypatch.setattr(main, "repository_list_analysis_runs", fake_list)

    response = client.get(
        "/analysis-runs?brand=%E3%82%B5%E3%82%A4%E3%83%9C%E3%82%A6%E3%82%BA&status=completed",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["total"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["brandName"] == "サイボウズ"
    assert "result" not in item
    assert "resultJson" not in item
    assert "meta" not in item
    assert calls[0]["brand"] == "サイボウズ"
    assert calls[0]["status"] == "completed"


def test_list_success_default_query_params(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(main, "repository_list_analysis_runs", fake_list)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert calls[0] == {"limit": 20, "offset": 0, "brand": None, "status": None}


def test_list_invalid_limit_is_rejected_before_read_history_check(monkeypatch):
    """FastAPI's own query validation (limit<=100) fires even when the
    read API is disabled and no token is sent — the same {"error": ...}
    shape as /analyze's existing validation errors (see main.py's
    validation_exception_handler)."""
    _clear_read_env(monkeypatch)

    response = client.get("/analysis-runs?limit=1000")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


def test_detail_success_includes_result(monkeypatch):
    _enable_read_env(monkeypatch)
    fake_detail = {
        "id": "11111111-1111-1111-1111-111111111111",
        "brand": {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "サイボウズ",
            "canonicalDomain": "cybozu.co.jp",
        },
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "サイボウズ"},
            "sourceSummary": {"web_fetch": 1},
            "startedAt": "2026-09-09T00:00:00+09:00",
            "completedAt": "2026-09-09T00:00:10+09:00",
        },
        "result": {
            "brandSummary": {},
            "cooccurrenceRanking": [],
            "contextAnalysis": [],
            "improvements": [],
            "aiOverviewComparison": [],
            "meta": {},
        },
        "meta": {"documentsSource": "web_fetch"},
    }
    monkeypatch.setattr(
        main, "repository_get_analysis_run", lambda analysis_run_id: fake_detail
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["brand"]["name"] == "サイボウズ"
    assert body["result"] == fake_detail["result"]
    assert body["meta"] == fake_detail["meta"]


# --- /analyze schema is untouched by this feature ---------------------------


def test_analyze_response_analysis_run_id_unaffected_by_read_api(monkeypatch):
    """Belt-and-suspenders alongside
    tests/test_main_analysis_history.py's equivalent checks — the read
    API added by this test file must not affect result.analysisRunId
    (added separately by docs/23_analysis_run_id_and_post_analyze_link_design.md's
    implementation). Without DB save configured, it's present and null,
    and it's never duplicated onto `meta`."""
    monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert body["analysisRunId"] is None
    assert "analysisRunId" not in body.get("meta", {})


def test_analyze_unaffected_by_history_read_token_gate(monkeypatch):
    """/analyze must keep working exactly as before even when
    HISTORY_READ_TOKEN is configured — the token gate applies only to
    the read API, never to /analyze."""
    _enable_read_env(monkeypatch)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200


# --- JWT verification + project access wired into the history API --------
#
# See docs/32_backend_jwt_verification_design.md "16"/"17" — main.py's
# _resolve_history_access() now actually calls services/jwt_auth.py and
# services/project_access.py when AUTH_JWT_ENABLED=true and
# HISTORY_READ_TOKEN doesn't pass. These tests mock main's own imported
# names (main.verify_supabase_jwt, main.open_history_db_connection,
# main.get_accessible_project_ids, main.can_user_access_analysis_run)
# rather than re-deriving real RSA/JWKS material — services/jwt_auth.py's
# own crypto correctness is already covered by tests/test_jwt_auth.py;
# this file's job is to verify main.py's wiring, status-code mapping,
# and project scoping.


class _FakeHistoryDbConnection:
    """Stand-in for the object returned by
    main.open_history_db_connection() — only used as a `with ... as
    conn:` context manager; the `conn` value itself is never inspected
    since services.project_access.py's functions are mocked too."""

    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_jwt_dependencies(
    monkeypatch,
    *,
    user_id: str = "user-1",
    project_ids: list[str] | None = None,
    can_access_run: bool = True,
):
    """Wires main's JWT/project-access dependencies to succeed with a
    fixed user_id/project_ids, for tests that don't care about
    jwt_auth.py's own crypto."""
    monkeypatch.setattr(
        main,
        "verify_supabase_jwt",
        lambda token, settings: AuthenticatedUser(user_id=user_id),
    )
    monkeypatch.setattr(
        main, "open_history_db_connection", lambda: _FakeHistoryDbConnection()
    )
    monkeypatch.setattr(
        main,
        "get_accessible_project_ids",
        lambda conn, uid: project_ids if project_ids is not None else [],
    )
    monkeypatch.setattr(
        main,
        "can_user_access_analysis_run",
        lambda conn, uid, run_id: can_access_run,
    )


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- AUTH_JWT_ENABLED=false: JWT path is fully inert -----------------------


def test_list_ignores_valid_looking_jwt_when_auth_jwt_disabled(monkeypatch):
    """A well-formed Authorization header must not be consulted at all
    when AUTH_JWT_ENABLED is unset/false — the request is denied
    exactly as it always was, with no attempt to verify the JWT."""
    _enable_read_env(monkeypatch)
    monkeypatch.delenv("AUTH_JWT_ENABLED", raising=False)
    verify_calls = []
    monkeypatch.setattr(
        main,
        "verify_supabase_jwt",
        lambda token, settings: verify_calls.append(token) or AuthenticatedUser(user_id="x"),
    )

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 403
    assert verify_calls == []


# --- AUTH_JWT_ENABLED=true, JWT verification unavailable -> 503 -----------


def test_list_returns_503_when_jwt_enabled_but_jwks_not_configured(monkeypatch):
    """AUTH_JWT_ENABLED=true with SUPABASE_JWKS_URL unset must not
    silently fall through to granting or denying access as if nothing
    were configured — the real (unmocked) verify_supabase_jwt() raises
    JWTAuthError("not_configured", ...), which main.py maps to 503, not
    401 or 403, so an operator can tell "server misconfigured" apart
    from "your token is bad"."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 503
    assert "error" in response.json()


def test_detail_returns_503_when_jwt_enabled_but_jwks_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_jwt_headers(),
    )

    assert response.status_code == 503
    assert "error" in response.json()


# --- AUTH_JWT_ENABLED=true, HISTORY_READ_TOKEN still takes precedence -----


def test_list_history_read_token_takes_precedence_over_jwt(monkeypatch):
    """A correct HISTORY_READ_TOKEN must grant the same unrestricted,
    unfiltered access as before this task, even when AUTH_JWT_ENABLED
    is on and an Authorization header is also present — this is what
    keeps the existing frontend proxy's requests working unchanged."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    verify_calls = []
    monkeypatch.setattr(
        main,
        "verify_supabase_jwt",
        lambda token, settings: verify_calls.append(token) or AuthenticatedUser(user_id="x"),
    )
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    headers = {**_auth_headers(), **_jwt_headers()}
    response = client.get("/analysis-runs", headers=headers)

    assert response.status_code == 200
    assert verify_calls == []
    # No project_ids key at all — identical call shape to the existing
    # history_token path (see test_list_success_default_query_params).
    assert calls[0] == {"limit": 20, "offset": 0, "brand": None, "status": None}


# --- AUTH_JWT_ENABLED=true, valid JWT: list is project-scoped --------------


def test_list_returns_only_accessible_projects_runs(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, project_ids=["project-1", "project-2"])
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 200
    assert calls[0]["project_ids"] == ["project-1", "project-2"]


def test_list_returns_empty_when_no_accessible_projects(monkeypatch):
    """An empty accessible-project list must yield an empty result, not
    an error and not the unrestricted list — proving a JWT alone (with
    zero project memberships) can never return any history."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, project_ids=[])
    # Deliberately not monkeypatching repository_list_analysis_runs —
    # the real function's project_ids=[] short-circuit (see
    # tests/test_analysis_history_repository.py) must return [] without
    # touching the DB at all, so this is safe to leave unmocked.

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json()["items"] == []


# --- AUTH_JWT_ENABLED=true, valid JWT: detail is access-checked ------------


def test_detail_returns_run_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    fake_detail = {
        "id": "11111111-1111-1111-1111-111111111111",
        "brand": {"id": "22222222-2222-2222-2222-222222222222", "name": "サイボウズ", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {},
            "sourceSummary": None,
            "startedAt": None,
            "completedAt": None,
        },
        "result": {
            "brandSummary": {},
            "cooccurrenceRanking": [],
            "contextAnalysis": [],
            "improvements": [],
            "aiOverviewComparison": [],
            "meta": {},
        },
        "meta": None,
        "projectId": "project-1",
    }
    monkeypatch.setattr(
        main, "repository_get_analysis_run", lambda analysis_run_id: fake_detail
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_jwt_headers(),
    )

    assert response.status_code == 200
    assert response.json()["brand"]["name"] == "サイボウズ"


def test_detail_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling repository_get_analysis_run() — a caller who
    can't see a run must not learn whether it exists either."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    detail_calls = []
    monkeypatch.setattr(
        main,
        "repository_get_analysis_run",
        lambda analysis_run_id: detail_calls.append(analysis_run_id),
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_jwt_headers(),
    )

    assert response.status_code == 403
    assert detail_calls == []


# --- AUTH_JWT_ENABLED=true, valid JWT: comparison is access-checked -------


def test_comparison_returns_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_get_analysis_run",
        lambda analysis_run_id: {
            "id": analysis_run_id,
            "run": {"startedAt": "2026-09-12T00:00:00+09:00"},
            "result": {"visibilityScore": 90},
            "projectId": "project-1",
        },
    )
    monkeypatch.setattr(
        main,
        "repository_get_previous_analysis_run_for_brand",
        lambda analysis_run_id, project_id=None: None,
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111/comparison",
        headers=_jwt_headers(),
    )

    assert response.status_code == 200
    assert response.json()["previous"] is None


def test_comparison_returns_403_when_run_inaccessible(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    detail_calls = []
    monkeypatch.setattr(
        main,
        "repository_get_analysis_run",
        lambda analysis_run_id: detail_calls.append(analysis_run_id),
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111/comparison",
        headers=_jwt_headers(),
    )

    assert response.status_code == 403
    assert detail_calls == []


def test_comparison_previous_lookup_is_scoped_to_current_runs_project(monkeypatch):
    """The previous-run lookup must be called with the *current* run's
    own project_id in JWT mode — this is what keeps a comparison from
    ever surfacing a run outside the project the caller was already
    authorized to see (docs/32_backend_jwt_verification_design.md
    "project境界"), even though can_user_access_analysis_run() only
    checked the current run."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_get_analysis_run",
        lambda analysis_run_id: {
            "id": analysis_run_id,
            "run": {"startedAt": "2026-09-12T00:00:00+09:00"},
            "result": {"visibilityScore": 90},
            "projectId": "project-current",
        },
    )
    previous_calls = []

    def fake_get_previous(analysis_run_id, project_id=None):
        previous_calls.append({"analysis_run_id": analysis_run_id, "project_id": project_id})
        return None

    monkeypatch.setattr(
        main, "repository_get_previous_analysis_run_for_brand", fake_get_previous
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111/comparison",
        headers=_jwt_headers(),
    )

    assert response.status_code == 200
    assert previous_calls[0]["project_id"] == "project-current"


def test_comparison_previous_lookup_unscoped_in_history_token_mode(monkeypatch):
    """The existing HISTORY_READ_TOKEN path must keep passing
    project_id=None (today's unrestricted brand-only matching) —
    confirms the new project scoping is exclusive to JWT mode."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "repository_get_analysis_run",
        lambda analysis_run_id: {
            "id": analysis_run_id,
            "run": {"startedAt": "2026-09-12T00:00:00+09:00"},
            "result": {"visibilityScore": 90},
            "projectId": "project-current",
        },
    )
    previous_calls = []

    def fake_get_previous(analysis_run_id, project_id=None):
        previous_calls.append({"project_id": project_id})
        return None

    monkeypatch.setattr(
        main, "repository_get_previous_analysis_run_for_brand", fake_get_previous
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111/comparison",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert previous_calls[0]["project_id"] is None


# --- JWT verification failures -> 401 --------------------------------------


def test_list_returns_401_for_malformed_authorization_header(monkeypatch):
    """A header that isn't the Bearer scheme fails inside
    extract_bearer_token() before verify_supabase_jwt() is ever
    called."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    verify_calls = []
    monkeypatch.setattr(
        main,
        "verify_supabase_jwt",
        lambda token, settings: verify_calls.append(token) or AuthenticatedUser(user_id="x"),
    )

    response = client.get(
        "/analysis-runs", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )

    assert response.status_code == 401
    assert verify_calls == []


def test_list_returns_401_for_invalid_jwt(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_signature", "token signature is invalid")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 401
    assert "error" in response.json()


def test_list_returns_401_for_expired_jwt(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    def raise_expired(token, settings):
        raise JWTAuthError("expired", "token has expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_expired)

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 401
    assert "error" in response.json()


def test_list_returns_503_when_jwks_fetch_fails(monkeypatch):
    """A runtime failure to reach the JWKS endpoint is a server-side
    availability problem, not the caller's fault — 503, not 401."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    def raise_fetch_failed(token, settings):
        raise JWTAuthError("jwks_fetch_failed", "failed to fetch signing keys")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_fetch_failed)

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 503


def test_list_returns_503_when_project_access_lookup_fails(monkeypatch):
    """A DB failure while resolving accessible projects must fail
    closed (503) — never silently proceed as if the caller had no/all
    projects."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.setattr(
        main,
        "verify_supabase_jwt",
        lambda token, settings: AuthenticatedUser(user_id="user-1"),
    )
    monkeypatch.setattr(
        main, "open_history_db_connection", lambda: _FakeHistoryDbConnection()
    )

    def raise_lookup_error(conn, user_id):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(main, "get_accessible_project_ids", raise_lookup_error)

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 503


def test_jwt_token_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_token", "token could not be verified")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)
    secret_token = "super-secret-jwt-value"

    response = client.get(
        "/analysis-runs", headers={"Authorization": f"Bearer {secret_token}"}
    )

    assert secret_token not in response.text
