"""Verifies GET /analysis-runs and GET /analysis-runs/{id} (see main.py,
docs/20_analysis_history_read_api_design.md), including the
HISTORY_READ_TOKEN gate added on top of READ_HISTORY_ENABLED (see
docs/24_auth_rls_history_access_design.md).

These tests never touch a real database — main.repository_list_analysis_runs
/ main.repository_get_analysis_run are monkeypatched at the main module
level (mirrors the existing main.fetch_url_texts / main.save_analysis_history
monkeypatch pattern in tests/test_main.py / tests/test_main_analysis_history.py).
READ_HISTORY_ENABLED/DATABASE_URL/HISTORY_READ_TOKEN env-var-driven skip
behavior itself is covered by tests/test_db_settings.py; list_analysis_runs()/
get_analysis_run()'s own query/error behavior is covered by
tests/test_analysis_history_repository.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER
from main import app
from services.analysis_history_repository import AnalysisHistoryReadError

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
