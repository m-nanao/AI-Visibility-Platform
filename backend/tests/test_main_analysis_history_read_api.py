"""Verifies GET /analysis-runs, GET /analysis-runs/{id}, and GET
/analysis-runs/{id}/comparison (see main.py,
docs/20_analysis_history_read_api_design.md), including the
HISTORY_READ_TOKEN gate added on top of READ_HISTORY_ENABLED (see
docs/24_auth_rls_history_access_design.md), the JWT verification +
project-access wiring added on top of that (see
docs/32_backend_jwt_verification_design.md "16"/"17"), and the
JWT-takes-precedence-when-present migration (see docs/32
"20").

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

import pytest
from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER
from main import app
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"


def _never_called(*args, **kwargs):
    raise AssertionError("this repository function must not be called")


@pytest.fixture(autouse=True)
def _default_count_analysis_runs(monkeypatch):
    """GET /analysis-runs now also calls repository_count_analysis_runs()
    for AnalysisRunListResponse.total (feature/history-server-side-
    search-pagination) — every test in this file that only cares about
    `items` gets a harmless default (0) here so it doesn't also have
    to mock the count call just to avoid a real DB connection attempt.
    A test that specifically wants to assert on `total` (see the
    dedicated tests below) overrides this with its own
    monkeypatch.setattr() afterward, which simply takes precedence."""
    monkeypatch.setattr(main, "repository_count_analysis_runs", lambda **kwargs: 0)


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
    # total is now a real count (feature/history-server-side-search-
    # pagination) — 0 here because repository_count_analysis_runs()
    # defaults to that for every test in this file (see the
    # _default_count_analysis_runs autouse fixture above) unless a
    # test specifically overrides it.
    assert body["total"] == 0
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["brandName"] == "サイボウズ"
    assert "result" not in item
    assert "resultJson" not in item
    assert "meta" not in item
    assert calls[0]["brand"] == "サイボウズ"
    assert calls[0]["status"] == "completed"


def test_list_success_includes_mode_summary_when_repository_provides_it(monkeypatch):
    fake_items = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brandName": "サイボウズ",
            "canonicalDomain": "cybozu.co.jp",
            "status": "completed",
            "visibilityScore": 86,
            "sourceSummary": None,
            "startedAt": "2026-09-09T00:00:00+09:00",
            "completedAt": "2026-09-09T00:00:10+09:00",
            "createdAt": "2026-09-09T00:00:10+09:00",
            "modeSummary": {
                "aiOverview": "live",
                "chatgpt": "real",
                "claude": "off",
                "gemini": "unavailable",
                "commonCrawl": "real",
            },
        }
    ]
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", lambda **kwargs: fake_items)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["modeSummary"] == {
        "aiOverview": "live",
        "chatgpt": "real",
        "claude": "off",
        "gemini": "unavailable",
        "commonCrawl": "real",
    }


def test_list_success_mode_summary_omitted_for_old_history(monkeypatch):
    """A repository row with no "modeSummary" key at all (e.g. a very
    old code path that predates this field) must not break the list
    response — modeSummary is simply absent/null on that item."""
    fake_items = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brandName": "サイボウズ",
            "canonicalDomain": None,
            "status": "completed",
            "visibilityScore": None,
            "sourceSummary": None,
            "startedAt": None,
            "completedAt": None,
            "createdAt": None,
        }
    ]
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", lambda **kwargs: fake_items)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["modeSummary"] is None


def test_list_success_includes_source_urls_when_repository_provides_them(monkeypatch):
    """sourceUrls (fix/history-domain-search) — derived from
    input_snapshot by the repository layer, forwarded as-is here."""
    fake_items = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brandName": "サイボウズ",
            "canonicalDomain": None,
            "status": "completed",
            "visibilityScore": 86,
            "sourceSummary": None,
            "startedAt": "2026-09-09T00:00:00+09:00",
            "completedAt": "2026-09-09T00:00:10+09:00",
            "createdAt": "2026-09-09T00:00:10+09:00",
            "sourceUrls": ["https://www.cybozu.co.jp/"],
        }
    ]
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", lambda **kwargs: fake_items)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["sourceUrls"] == ["https://www.cybozu.co.jp/"]


def test_list_success_source_urls_defaults_to_empty_list_for_old_history(monkeypatch):
    """A repository row with no "sourceUrls" key at all (older code
    path, or input_snapshot had no urls) must not break the list
    response — sourceUrls defaults to [], never omitted or null."""
    fake_items = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brandName": "サイボウズ",
            "canonicalDomain": None,
            "status": "completed",
            "visibilityScore": None,
            "sourceSummary": None,
            "startedAt": None,
            "completedAt": None,
            "createdAt": None,
        }
    ]
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", lambda **kwargs: fake_items)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["sourceUrls"] == []


def test_list_success_default_query_params(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(main, "repository_list_analysis_runs", fake_list)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert calls[0] == {
        "limit": 20,
        "offset": 0,
        "brand": None,
        "status": None,
        "search": None,
        "important": None,
        "started_from": None,
        "started_to": None,
        "ai_overview_observation": None,
        "chatgpt_observation": None,
        "claude_observation": None,
        "gemini_observation": None,
        "sort": "newest",
        "project_ids": None,
    }


def test_list_invalid_limit_is_rejected_before_read_history_check(monkeypatch):
    """FastAPI's own query validation (limit<=100) fires even when the
    read API is disabled and no token is sent — the same {"error": ...}
    shape as /analyze's existing validation errors (see main.py's
    validation_exception_handler)."""
    _clear_read_env(monkeypatch)

    response = client.get("/analysis-runs?limit=1000")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


# --- GET /analysis-runs: search/important/date-range/sort/total
# (feature/history-server-side-search-pagination) ---------------------------


def test_list_passes_search_important_and_sort_through_to_the_repository(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get(
        "/analysis-runs?search=cybozu&important=true&sort=oldest", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert calls[0]["search"] == "cybozu"
    assert calls[0]["important"] is True
    assert calls[0]["sort"] == "oldest"


def test_list_unrecognized_sort_value_falls_back_to_newest(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get("/analysis-runs?sort=sideways", headers=_auth_headers())

    assert response.status_code == 200
    assert calls[0]["sort"] == "newest"


def test_list_accepts_valid_started_from_and_started_to(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get(
        "/analysis-runs?startedFrom=2026-10-01T00:00:00%2B09:00"
        "&startedTo=2026-10-02T00:00:00%2B09:00",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    started_from = calls[0]["started_from"]
    started_to = calls[0]["started_to"]
    assert started_from.isoformat() == "2026-10-01T00:00:00+09:00"
    assert started_to.isoformat() == "2026-10-02T00:00:00+09:00"


def test_list_rejects_started_from_without_a_timezone_offset(monkeypatch):
    """A naive (no-offset) datetime is rejected rather than guessed at
    — assuming either UTC or JST here could silently shift the
    caller's intended day boundary by 9 hours."""
    _enable_read_env(monkeypatch)

    response = client.get(
        "/analysis-runs?startedFrom=2026-10-01T00:00:00", headers=_auth_headers()
    )

    assert response.status_code == 400
    assert "startedFrom" in response.json()["error"]


def test_list_rejects_an_unparseable_started_to(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get("/analysis-runs?startedTo=not-a-date", headers=_auth_headers())

    assert response.status_code == 400
    assert "startedTo" in response.json()["error"]


def test_list_passes_ai_observation_filters_through_to_the_repository(monkeypatch):
    """feature/history-ai-observation-filter: the 4 new query params
    pass straight through to list_analysis_runs() under their
    snake_case kwarg names."""
    _enable_read_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get(
        "/analysis-runs?aiOverviewObservation=mentioned"
        "&chatgptObservation=not_mentioned"
        "&claudeObservation=off"
        "&geminiObservation=unavailable",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert calls[0]["ai_overview_observation"] == "mentioned"
    assert calls[0]["chatgpt_observation"] == "not_mentioned"
    assert calls[0]["claude_observation"] == "off"
    assert calls[0]["gemini_observation"] == "unavailable"


def test_list_unknown_ai_observation_filter_value_is_accepted(monkeypatch):
    _enable_read_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    response = client.get(
        "/analysis-runs?aiOverviewObservation=unknown", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert calls[0]["ai_overview_observation"] == "unknown"


def test_list_rejects_an_invalid_ai_observation_filter_value(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", _never_called)

    response = client.get(
        "/analysis-runs?chatgptObservation=sideways", headers=_auth_headers()
    )

    assert response.status_code == 400
    assert "chatgptObservation" in response.json()["error"]


def test_list_invalid_started_from_is_rejected_before_touching_the_repository(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", _never_called)

    response = client.get(
        "/analysis-runs?startedFrom=2026-10-01T00:00:00", headers=_auth_headers()
    )

    assert response.status_code == 400


def test_list_response_includes_the_total_count_from_the_repository(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_list_analysis_runs", lambda **kwargs: [])
    monkeypatch.setattr(main, "repository_count_analysis_runs", lambda **kwargs: 123)

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["total"] == 123


def test_list_count_receives_the_same_filters_as_list_including_project_ids(monkeypatch):
    """The count call must see exactly the same project_ids/search/
    important/date filters the list call does — a mismatch here would
    let `total` disagree with (or leak beyond) what `items` can ever
    actually show across pages."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, project_ids=["project-1", "project-2"])
    list_calls = []
    count_calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: list_calls.append(kwargs) or []
    )
    monkeypatch.setattr(
        main,
        "repository_count_analysis_runs",
        lambda **kwargs: count_calls.append(kwargs) or 0,
    )

    response = client.get("/analysis-runs?search=cybozu&important=true", headers=_jwt_headers())

    assert response.status_code == 200
    # Same filter-relevant keys on both calls (list carries limit/
    # offset/sort too, which count() doesn't take at all).
    for key in (
        "project_ids",
        "search",
        "important",
        "brand",
        "status",
        "ai_overview_observation",
        "chatgpt_observation",
        "claude_observation",
        "gemini_observation",
    ):
        assert list_calls[0][key] == count_calls[0][key]


def test_list_count_short_circuits_with_list_when_no_accessible_projects(monkeypatch):
    """main.py always calls both repository functions unconditionally
    — the "no accessible projects" short-circuit (return []/0 without
    touching the DB at all) lives inside
    list_analysis_runs()/count_analysis_runs() themselves (see
    tests/test_analysis_history_repository.py's dedicated tests for
    that), not in main.py. This only verifies the two calls still
    agree on `project_ids=[]` and that the resulting response is a
    well-formed empty page, not a 503/error."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, project_ids=[])
    list_calls = []
    count_calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: list_calls.append(kwargs) or []
    )
    monkeypatch.setattr(
        main,
        "repository_count_analysis_runs",
        lambda **kwargs: count_calls.append(kwargs) or 0,
    )

    response = client.get("/analysis-runs", headers=_jwt_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert list_calls[0]["project_ids"] == []
    assert count_calls[0]["project_ids"] == []


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


def test_detail_includes_project_id_when_present(monkeypatch):
    """feature/async-job-failure-display-and-retry: the frontend's
    "re-run this analysis" action needs the run's own project id to
    submit a new job against — see AnalysisRunDetailResponse.projectId's
    docstring for why exposing it here is not a new authorization
    grant (the caller already passed this run's own access check to
    get this response at all)."""
    _enable_read_env(monkeypatch)
    fake_detail = {
        "id": "11111111-1111-1111-1111-111111111111",
        "brand": {"id": "22222222-2222-2222-2222-222222222222", "name": "サイボウズ", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "サイボウズ"},
            "sourceSummary": None,
            "startedAt": None,
            "completedAt": None,
        },
        "result": {},
        "meta": None,
        "projectId": "33333333-3333-3333-3333-333333333333",
    }
    monkeypatch.setattr(
        main, "repository_get_analysis_run", lambda analysis_run_id: fake_detail
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["projectId"] == "33333333-3333-3333-3333-333333333333"


def test_detail_project_id_is_null_for_a_legacy_run(monkeypatch):
    _enable_read_env(monkeypatch)
    fake_detail = {
        "id": "11111111-1111-1111-1111-111111111111",
        "brand": {"id": "22222222-2222-2222-2222-222222222222", "name": "サイボウズ", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "サイボウズ"},
            "sourceSummary": None,
            "startedAt": None,
            "completedAt": None,
        },
        "result": {},
        "meta": None,
        # No "projectId" key at all — mirrors a row saved before
        # 002_add_organizations_projects.sql, or any other legacy shape
        # the repository might still return it without.
    }
    monkeypatch.setattr(
        main, "repository_get_analysis_run", lambda analysis_run_id: fake_detail
    )

    response = client.get(
        "/analysis-runs/11111111-1111-1111-1111-111111111111",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["projectId"] is None


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


# --- AUTH_JWT_ENABLED=true, Authorization present: JWT now takes ----------
# --- precedence over HISTORY_READ_TOKEN (docs/32 "20") --------------------


def test_list_jwt_takes_precedence_over_history_read_token_when_both_present(monkeypatch):
    """When AUTH_JWT_ENABLED is on and the request carries both a
    correct HISTORY_READ_TOKEN and an Authorization header, the JWT
    path must be used (and the request must be project-scoped) —
    HISTORY_READ_TOKEN is only ever consulted when there is no
    Authorization header at all. This is what lets the frontend
    proxy's real production requests (which send both headers)
    actually exercise the JWT/project-access path."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, project_ids=["project-1"])
    calls = []
    monkeypatch.setattr(
        main, "repository_list_analysis_runs", lambda **kwargs: calls.append(kwargs) or []
    )

    headers = {**_auth_headers(), **_jwt_headers()}
    response = client.get("/analysis-runs", headers=headers)

    assert response.status_code == 200
    # project_ids is present and reflects the JWT-derived membership —
    # proof the JWT/project-access path ran rather than the
    # unrestricted history_token path.
    assert calls[0]["project_ids"] == ["project-1"]


def test_list_returns_401_for_invalid_jwt_even_with_history_read_token_present(monkeypatch):
    """An invalid JWT must not fall back to a correct, simultaneously
    present HISTORY_READ_TOKEN — a broken JWT path must surface as an
    error, not silently degrade to the legacy gate."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_signature", "token signature is invalid")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)

    headers = {**_auth_headers(), **_jwt_headers()}
    response = client.get("/analysis-runs", headers=headers)

    assert response.status_code == 401


def test_list_returns_503_when_jwt_unconfigured_even_with_history_read_token_present(monkeypatch):
    """A misconfigured JWT path (SUPABASE_JWKS_URL unset) must not fall
    back to a correct, simultaneously present HISTORY_READ_TOKEN — a
    server misconfiguration must be visible as 503, not masked by the
    legacy gate."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)

    headers = {**_auth_headers(), **_jwt_headers()}
    response = client.get("/analysis-runs", headers=headers)

    assert response.status_code == 503


# --- AUTH_JWT_ENABLED=true, no Authorization header: HISTORY_READ_TOKEN ---
# --- fallback is preserved -------------------------------------------------


def test_list_history_token_mode_when_auth_jwt_enabled_but_no_authorization_header(monkeypatch):
    """With no Authorization header at all, AUTH_JWT_ENABLED=true must
    not change anything — a correct HISTORY_READ_TOKEN still grants
    the same unrestricted, unfiltered access as before this task."""
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

    response = client.get("/analysis-runs", headers=_auth_headers())

    assert response.status_code == 200
    assert verify_calls == []
    # project_ids=None (not omitted) — the endpoint now always passes
    # this key explicitly (None in history_token mode, the caller's
    # accessible-project list in jwt mode) so the same filter-kwargs
    # dict can be shared between the list and count calls; identical
    # call shape to the existing history_token path either way (see
    # test_list_success_default_query_params).
    assert calls[0] == {
        "limit": 20,
        "offset": 0,
        "brand": None,
        "status": None,
        "search": None,
        "important": None,
        "started_from": None,
        "started_to": None,
        "ai_overview_observation": None,
        "chatgpt_observation": None,
        "claude_observation": None,
        "gemini_observation": None,
        "sort": "newest",
        "project_ids": None,
    }


def test_list_returns_403_when_auth_jwt_enabled_and_no_credentials_at_all(monkeypatch):
    """AUTH_JWT_ENABLED=true with neither an Authorization header nor a
    HISTORY_READ_TOKEN header must still be denied (403), same as
    before this task."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")

    response = client.get("/analysis-runs")

    assert response.status_code == 403


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
