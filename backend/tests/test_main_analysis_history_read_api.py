"""Verifies GET /analysis-runs and GET /analysis-runs/{id} (see main.py,
docs/20_analysis_history_read_api_design.md).

These tests never touch a real database — main.repository_list_analysis_runs
/ main.repository_get_analysis_run are monkeypatched at the main module
level (mirrors the existing main.fetch_url_texts / main.save_analysis_history
monkeypatch pattern in tests/test_main.py / tests/test_main_analysis_history.py).
READ_HISTORY_ENABLED/DATABASE_URL env-var-driven skip behavior itself is
covered by tests/test_db_settings.py; list_analysis_runs()/get_analysis_run()'s
own query/error behavior is covered by tests/test_analysis_history_repository.py.
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import AnalysisHistoryReadError

client = TestClient(app)


def _clear_read_env(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _enable_read_env(monkeypatch):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")


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

    response = client.get("/analysis-runs")

    assert response.status_code == 503


def test_db_save_enabled_alone_does_not_enable_read_api(monkeypatch):
    """DB_SAVE_ENABLED=true (with DATABASE_URL set) must not enable the
    read API by itself — READ_HISTORY_ENABLED is a separate flag."""
    monkeypatch.setenv("DB_SAVE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)

    response = client.get("/analysis-runs")

    assert response.status_code == 503


# --- repository failure → 503 ----------------------------------------------


def test_list_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_list(**kwargs):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_list_analysis_runs", raising_list)

    response = client.get("/analysis-runs")

    assert response.status_code == 503


def test_detail_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_get(analysis_run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 503


# --- not found → 404 --------------------------------------------------------


def test_detail_returns_404_when_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: None)

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 404


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

    response = client.get("/analysis-runs?brand=%E3%82%B5%E3%82%A4%E3%83%9C%E3%82%A6%E3%82%BA&status=completed")

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

    response = client.get("/analysis-runs")

    assert response.status_code == 200
    assert calls[0] == {"limit": 20, "offset": 0, "brand": None, "status": None}


def test_list_invalid_limit_is_rejected_before_read_history_check(monkeypatch):
    """FastAPI's own query validation (limit<=100) fires even when the
    read API is disabled — the same {"error": ...} shape as /analyze's
    existing validation errors (see main.py's validation_exception_handler)."""
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

    response = client.get("/analysis-runs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    body = response.json()
    assert body["brand"]["name"] == "サイボウズ"
    assert body["result"] == fake_detail["result"]
    assert body["meta"] == fake_detail["meta"]


# --- /analyze schema is untouched by this feature ---------------------------


def test_analyze_response_still_has_no_analysis_run_id(monkeypatch):
    """Belt-and-suspenders alongside
    tests/test_main_analysis_history.py's equivalent check — this task
    adds a read API but must not touch /analyze's response shape."""
    monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert "analysisRunId" not in body
    assert "analysisRunId" not in body.get("meta", {})
