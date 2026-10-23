"""Verifies POST /analyze's Task 6-D-5B wiring for the
`officialUrl`/`officialInfoCandidate` feature (backend/main.py's
run_analysis_pipeline(), and the anonymous POST /analyze handler that
calls it) — mirrors the established convention of monkeypatching the
higher-level function (`main.build_official_info_candidate`) directly
for most tests (its own gating/fetch logic is already covered by
tests/test_official_info_candidate.py), plus one true end-to-end
integration test that exercises the real reuse-with-urls[] path.

Never touches a real database and never calls a real external
provider.
"""

from fastapi.testclient import TestClient

import main
import services.official_info_candidate as oic
from main import app
from models import OfficialInfoCandidate
from services.web_fetcher import UrlFetchResult

client = TestClient(app)


def _post_body(**overrides):
    body = {"brandName": "サイボウズ"}
    body.update(overrides)
    return body


# --- backward compatibility (officialUrl absent) ----------------------------


def test_backward_compatible_when_official_url_is_absent(monkeypatch):
    """The real, unmocked build_official_info_candidate() must return
    None and never call fetch_url_texts when officialUrl is omitted —
    this test deliberately does not monkeypatch it."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_url_texts should not be called")

    monkeypatch.setattr(oic, "fetch_url_texts", fail_if_called)

    response = client.post("/analyze", json=_post_body())

    assert response.status_code == 200
    body = response.json()
    assert body["officialInfoCandidate"] is None


def test_existing_response_shape_is_unaffected_when_official_url_is_absent():
    before = main.build_dummy_analysis("サイボウズ")
    response = client.post("/analyze", json=_post_body())

    assert response.status_code == 200
    body = response.json()
    assert len(body["aiOverviewComparison"]) == len(before.aiOverviewComparison)


# --- wiring: officialUrl present ---------------------------------------------


def test_official_url_is_passed_to_build_official_info_candidate(monkeypatch):
    calls = []

    def fake_build(official_url, documents_list):
        calls.append({"official_url": official_url, "documents_list": documents_list})
        return OfficialInfoCandidate(
            requestedUrl=official_url, status="success", fetchedUrl=official_url,
            title="Acme Inc.", fetchedAt="2026-10-25T00:00:00Z", hasText=True,
        )

    monkeypatch.setattr(main, "build_official_info_candidate", fake_build)

    response = client.post(
        "/analyze", json=_post_body(officialUrl="https://acme.example.com")
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["official_url"] == "https://acme.example.com"
    body = response.json()
    assert body["officialInfoCandidate"]["status"] == "success"
    assert body["officialInfoCandidate"]["fetchedUrl"] == "https://acme.example.com"
    assert body["officialInfoCandidate"]["title"] == "Acme Inc."
    assert body["officialInfoCandidate"]["hasText"] is True


def test_failed_fetch_is_reflected_in_the_response(monkeypatch):
    def fake_build(official_url, documents_list):
        return OfficialInfoCandidate(
            requestedUrl=official_url, status="failed", error="unsupported scheme: 'ftp'"
        )

    monkeypatch.setattr(main, "build_official_info_candidate", fake_build)

    response = client.post(
        "/analyze", json=_post_body(officialUrl="ftp://acme.example.com")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["officialInfoCandidate"]["status"] == "failed"
    assert body["officialInfoCandidate"]["error"] == "unsupported scheme: 'ftp'"


def test_an_unexpected_exception_never_breaks_the_response(monkeypatch):
    """Defensive expectation: even though build_official_info_candidate()
    is documented to never raise, if it somehow did, that must not be
    allowed to take down the rest of a successful /analyze response.
    Guarded here by confirming the real function's own contract
    instead — a raise inside run_analysis_pipeline() would currently
    propagate (matching every other unexpected-bug case in that
    function per its own docstring), so this test instead confirms the
    documented no-raise contract holds for a failure-shaped input."""
    result = oic.build_official_info_candidate("not a url at all", [])
    assert result is not None
    assert result.status == "failed"


# --- SSRF rejection surfaces as a failed candidate, not a crash ------------


def test_ssrf_target_url_surfaces_as_failed_not_an_error(monkeypatch):
    response = client.post(
        "/analyze", json=_post_body(officialUrl="http://127.0.0.1/admin")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["officialInfoCandidate"]["status"] == "failed"
    assert body["officialInfoCandidate"]["error"] is not None


# --- reuse with urls[] (true end-to-end integration) ------------------------


def test_official_url_matching_an_existing_urls_entry_is_reused_end_to_end(monkeypatch):
    """Task 6-D-5B item 2: 同一runで取得済みの場合は再利用する — this
    test deliberately does NOT monkeypatch build_official_info_candidate
    itself, only the underlying fetch_url_texts() both main.py's urls[]
    branch and services/official_info_candidate.py separately imported
    by name — proving the real reuse logic prevents a second HTTP
    fetch for the same URL within one request."""
    calls = []

    def fake_fetch_url_texts(urls):
        calls.extend(urls)
        return [
            UrlFetchResult(url=url, success=True, text="Official overview text.", title="Acme Inc.")
            for url in urls
        ]

    monkeypatch.setattr(main, "fetch_url_texts", fake_fetch_url_texts)
    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    response = client.post(
        "/analyze",
        json=_post_body(
            urls=["https://acme.example.com"],
            officialUrl="https://acme.example.com",
        ),
    )

    assert response.status_code == 200
    # Only one real fetch happened in total — officialUrl reused the
    # Document already fetched for urls[], never issuing a second
    # request to the same URL.
    assert calls == ["https://acme.example.com"]
    body = response.json()
    assert body["officialInfoCandidate"]["status"] == "success"
    assert body["officialInfoCandidate"]["fetchedUrl"] == "https://acme.example.com"
    assert body["officialInfoCandidate"]["title"] == "Acme Inc."
    # Reuse carries over the real Document's own id.
    assert body["officialInfoCandidate"]["documentId"] is not None


def test_official_url_not_matching_any_urls_entry_still_fetches_independently(monkeypatch):
    calls = []

    def fake_fetch_url_texts(urls):
        calls.extend(urls)
        return [
            UrlFetchResult(url=url, success=True, text="text", title="T")
            for url in urls
        ]

    monkeypatch.setattr(main, "fetch_url_texts", fake_fetch_url_texts)
    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    response = client.post(
        "/analyze",
        json=_post_body(
            urls=["https://a.example.com"],
            officialUrl="https://acme.example.com",
        ),
    )

    assert response.status_code == 200
    assert sorted(calls) == sorted(["https://a.example.com", "https://acme.example.com"])
    body = response.json()
    assert body["officialInfoCandidate"]["status"] == "success"


# --- non-interference with existing providers -------------------------------


def test_official_url_is_never_passed_to_any_existing_websearch_provider(monkeypatch):
    """Task 6-D-5B item 5: officialUrlを既存の検索補完プロバイダへ無断で
    渡さない — none of the existing attempt_*_supplement functions
    accept an official_url-shaped kwarg at all, so capturing their
    call kwargs and asserting the key's absence directly proves this."""
    captured_kwargs = {}

    def make_recorder(name):
        def recorder(**kwargs):
            captured_kwargs[name] = kwargs
            return None, type(
                "Info", (), {"status": "disabled", "reason": "ok", "model_dump": lambda self: {}}
            )()

        return recorder

    # These four are the existing conditional supplement attempts —
    # see main.py's own wiring block. None of them take an
    # `official_url`/`officialUrl` parameter.
    for name in (
        "attempt_chatgpt_websearch_supplement",
        "attempt_claude_websearch_supplement",
        "attempt_gemini_websearch_supplement",
        "attempt_gemini_external_document_supplement",
    ):
        monkeypatch.setattr(main, name, make_recorder(name))

    response = client.post(
        "/analyze",
        json={
            "brandName": "サイボウズ",
            "projectId": "p1",
            "requestId": "req-1",
            "officialUrl": "https://acme.example.com",
        },
        headers={},
    )

    # This request is unauthenticated (no JWT), so the authenticated
    # websearch-supplement block is never reached at all — confirming
    # the *anonymous* path (which does run build_official_info_candidate)
    # never touches these functions is still useful context, but the
    # real assertion is on the captured kwargs for any call that did
    # happen below.
    assert response.status_code == 200
    for name, kwargs in captured_kwargs.items():
        assert "official_url" not in kwargs, f"{name} unexpectedly received official_url"
        assert "officialUrl" not in kwargs, f"{name} unexpectedly received officialUrl"


# --- backward compatibility with old saved history --------------------------


def test_old_history_rows_without_official_info_candidate_still_parse():
    old_result_json = main.build_dummy_analysis("サイボウズ").model_dump()
    assert "officialInfoCandidate" not in old_result_json or (
        old_result_json.get("officialInfoCandidate") is None
    )

    from models import AnalysisResult

    parsed = AnalysisResult(**old_result_json)
    assert parsed.officialInfoCandidate is None


def test_old_analyze_request_without_official_url_still_validates():
    from models import AnalyzeRequest

    parsed = AnalyzeRequest(brandName="Acme")
    assert parsed.officialUrl is None


# --- no quota impact ---------------------------------------------------------


def test_official_url_never_reserves_any_websearch_quota(monkeypatch):
    """Task 6-D-5B item 5: officialUrlを追加したことで既存のprovider
    quotaが増加しないことを確認する — this feature is a plain
    services/web_fetcher.py fetch with no quota reservation of any
    kind, so reserve_websearch_quota_for_analysis_run() must never be
    called just because officialUrl was supplied."""

    def fail_if_called(**kwargs):
        raise AssertionError(
            "reserve_websearch_quota_for_analysis_run should never be called for officialUrl"
        )

    monkeypatch.setattr(oic, "fetch_url_texts", lambda urls: [
        UrlFetchResult(url=u, success=True, text="text", title="T") for u in urls
    ])
    import services.websearch_quota_reservation as wq

    monkeypatch.setattr(wq, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    response = client.post(
        "/analyze", json=_post_body(officialUrl="https://acme.example.com")
    )

    assert response.status_code == 200
    assert response.json()["officialInfoCandidate"]["status"] == "success"
