"""Verifies /analyze's integration with services.analysis_history_repository
(see main.py's call to save_analysis_history() near the end of analyze()),
including the resulting result.analysisRunId field (see
docs/23_analysis_run_id_and_post_analyze_link_design.md).

These tests never touch a real database — save_analysis_history() is
monkeypatched at the main module level (mirrors the existing
main.fetch_url_texts monkeypatch pattern in tests/test_main.py). DB
env-var-driven skip/enable behavior itself is covered by
tests/test_db_settings.py and tests/test_analysis_history_repository.py.
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import AnalysisHistorySaveResult

client = TestClient(app)


def test_analyze_succeeds_when_db_save_not_configured(monkeypatch):
    """Default env (no DB_SAVE_ENABLED/DATABASE_URL): /analyze must
    behave exactly as before this feature existed, aside from the new
    analysisRunId field being present and null."""
    monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    assert response.json()["analysisRunId"] is None


def test_analyze_calls_save_analysis_history_with_expected_arguments(monkeypatch):
    calls = []

    def fake_save_analysis_history(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(main, "save_analysis_history", fake_save_analysis_history)

    response = client.post(
        "/analyze",
        json={"brandName": "サイボウズ", "urls": ["https://cybozu.co.jp/"]},
    )

    assert response.status_code in (200, 502, 400)
    # Regardless of whether the url fetch itself succeeded, analyze()
    # always reaches the save_analysis_history() call on a successful
    # (200) response.
    if response.status_code == 200:
        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["brand_name"] == "サイボウズ"
        assert kwargs["input_snapshot"]["brandName"] == "サイボウズ"
        assert kwargs["input_snapshot"]["urls"] == ["https://cybozu.co.jp/"]
        assert kwargs["status"] in ("completed", "partial")
        assert isinstance(kwargs["result_json"], dict)
        assert isinstance(kwargs["meta_json"], dict)
        assert response.json()["analysisRunId"] is None


def test_analyze_succeeds_even_if_save_analysis_history_raises(monkeypatch):
    def raising_save_analysis_history(**kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(main, "save_analysis_history", raising_save_analysis_history)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert body["brandName"] == "サイボウズ"
    assert body["analysisRunId"] is None


def test_analyze_response_includes_analysis_run_id_on_save_success(monkeypatch):
    """When save_analysis_history() succeeds, its analysis_run_id is
    surfaced as result.analysisRunId — the whole point of this field."""

    def fake_save_analysis_history(**kwargs):
        return AnalysisHistorySaveResult(
            analysis_run_id="11111111-1111-1111-1111-111111111111",
            brand_id="22222222-2222-2222-2222-222222222222",
        )

    monkeypatch.setattr(main, "save_analysis_history", fake_save_analysis_history)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert body["analysisRunId"] == "11111111-1111-1111-1111-111111111111"
    # Main response fields are unaffected by the save outcome.
    assert body["brandName"] == "サイボウズ"


def test_analyze_response_has_null_analysis_run_id_when_save_disabled(monkeypatch):
    """DB_SAVE_ENABLED=false (or unset): save_analysis_history() itself
    returns None without attempting a connection — analysisRunId must
    be null, and /analyze must still succeed."""
    monkeypatch.setenv("DB_SAVE_ENABLED", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    assert response.json()["analysisRunId"] is None


def test_analyze_response_has_null_analysis_run_id_when_database_url_missing(monkeypatch):
    """DB_SAVE_ENABLED=true but DATABASE_URL unset: save is still
    skipped (services/db_settings.py requires both) — analysisRunId
    stays null and /analyze still succeeds."""
    monkeypatch.setenv("DB_SAVE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    assert response.json()["analysisRunId"] is None
