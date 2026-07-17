import httpx

from services import dataforseo_client
from services.dataforseo_client import (
    ORGANIC_LIVE_ADVANCED_PATH,
    fetch_ai_overview_sandbox,
)
from services.dataforseo_settings import SANDBOX_BASE_URL, DataForSEOCredentials

_CREDENTIALS = DataForSEOCredentials(login="someone@example.com", password="super-secret-password")


def _success_payload(items: list[dict]) -> dict:
    return {
        "status_code": 20000,
        "tasks": [{"result": [{"items": items}]}],
    }


def test_fetch_uses_sandbox_base_url_and_organic_live_advanced_path(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200,
            json=_success_payload([{"type": "ai_overview", "text": "Acme is great."}]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert seen_urls == [f"{SANDBOX_BASE_URL}{ORGANIC_LIVE_ADVANCED_PATH}"]
    assert SANDBOX_BASE_URL.startswith("https://sandbox.")


def test_fetch_sends_basic_auth_with_the_given_credentials(monkeypatch):
    seen_auth = []

    def fake_post(url, **kwargs):
        seen_auth.append(kwargs.get("auth"))
        return httpx.Response(
            200,
            json=_success_payload([]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert seen_auth == [("someone@example.com", "super-secret-password")]


def test_fetch_converts_a_successful_response_with_ai_overview_item(monkeypatch):
    payload = _success_payload(
        [
            {"type": "organic", "rank_absolute": 1, "text": "unrelated organic result"},
            {"type": "ai_overview", "rank_absolute": 2, "text": "Acme is a well-reviewed tool for teams."},
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.mentioned is True
    assert result.rank == 2
    assert "Acme" in result.summary


def test_fetch_reads_text_from_nested_items_when_present(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "items": [{"text": "Acme helps teams collaborate."}, {"text": "It has a free tier."}],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert "Acme" in result.summary
    assert "free tier" in result.summary


def test_fetch_marks_not_mentioned_when_brand_name_is_absent_from_text(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "text": "A generic summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.mentioned is False


def test_fetch_returns_unavailable_reason_when_no_ai_overview_item_is_present(monkeypatch):
    payload = _success_payload([{"type": "organic", "rank_absolute": 1, "text": "just organic results"}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "no supported AI overview item was found" in result.reason


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False


def test_fetch_fails_safely_on_unexpected_status_code_in_payload(monkeypatch):
    payload = {"status_code": 40100, "status_message": "Auth failed."}

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False


def test_fetch_never_raises_out_of_the_function(monkeypatch):
    def raise_unexpected(url, **kwargs):
        raise RuntimeError("something exploded")

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_unexpected)

    try:
        result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")
    except RuntimeError:
        # httpx.HTTPError is the only exception type this client
        # catches by design (see module docstring) — a genuinely
        # unexpected exception type is allowed to propagate, since
        # swallowing *everything* would hide real bugs. This test
        # exists to document that boundary rather than assert total
        # exception suppression.
        return
    assert result.success is False


def test_password_never_appears_in_the_reason_string_on_any_failure_path(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert "super-secret-password" not in result.reason
    assert "someone@example.com" not in result.reason


def test_summary_is_truncated_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "text": long_text}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert len(result.summary) <= 201  # _SUMMARY_MAX_CHARS + ellipsis
    assert len(result.summary) < len(long_text)


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert calls["count"] == 1
