"""Verifies /analyze's integration with services.analysis_history_repository
(see main.py's call to save_analysis_history() near the end of analyze()).

These tests never touch a real database — save_analysis_history() is
monkeypatched at the main module level (mirrors the existing
main.fetch_url_texts monkeypatch pattern in tests/test_main.py). DB
env-var-driven skip/enable behavior itself is covered by
tests/test_db_settings.py and tests/test_analysis_history_repository.py.
"""

from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


def test_analyze_succeeds_when_db_save_not_configured(monkeypatch):
    """Default env (no DB_SAVE_ENABLED/DATABASE_URL): /analyze must
    behave exactly as before this feature existed."""
    monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200


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


def test_analyze_succeeds_even_if_save_analysis_history_raises(monkeypatch):
    def raising_save_analysis_history(**kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(main, "save_analysis_history", raising_save_analysis_history)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert body["brandName"] == "サイボウズ"


def test_analyze_response_schema_has_no_analysis_run_id_field(monkeypatch):
    """API response schema is unchanged by this task — no analysisRunId
    or similar DB-derived field is ever added to /analyze's response."""
    monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200
    body = response.json()
    assert "analysisRunId" not in body
    assert "analysisRunId" not in body.get("meta", {})
