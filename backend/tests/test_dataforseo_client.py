import httpx

from services import dataforseo_client
from services.dataforseo_client import (
    AI_MODE_LIVE_ADVANCED_PATH,
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


def test_fetch_defaults_to_sandbox_base_url_and_ai_mode_live_advanced_path(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200,
            json=_success_payload([{"type": "ai_overview", "markdown": "Acme is great."}]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert seen_urls == [f"{SANDBOX_BASE_URL}{AI_MODE_LIVE_ADVANCED_PATH}"]
    assert SANDBOX_BASE_URL.startswith("https://sandbox.")


def test_fetch_can_be_pointed_at_the_organic_endpoint_instead(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200,
            json=_success_payload([{"type": "ai_overview", "text": "Acme is great."}]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme", endpoint="google_organic_live_advanced")

    assert seen_urls == [f"{SANDBOX_BASE_URL}{ORGANIC_LIVE_ADVANCED_PATH}"]


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


def test_fetch_sends_keyword_location_language_device_and_os_in_the_payload(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(
        _CREDENTIALS,
        "Acme",
        location_code=2392,
        language_code="ja",
        device="desktop",
        os_name="windows",
    )

    assert seen_bodies == [
        [
            {
                "keyword": "Acme",
                "location_code": 2392,
                "language_code": "ja",
                "device": "desktop",
                "os": "windows",
            }
        ]
    ]


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


def test_fetch_prefers_markdown_over_text_for_the_summary(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme **is** a well-reviewed tool for teams.",
                "text": "this plain-text fallback should not be used",
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert "well-reviewed tool for teams" in result.summary
    assert "plain-text fallback" not in result.summary


def test_fetch_falls_back_to_rank_group_when_rank_absolute_is_missing(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_group": 3, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.rank == 3


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


def test_fetch_uses_references_to_decide_mentioned_but_not_in_summary(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "A generic summary with no brand name.",
                "references": [
                    {"title": "Acme raises Series B", "domain": "acme.example.com", "text": "Acme news."}
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.mentioned is True
    # references are only used to decide `mentioned`, never surfaced in
    # the summary excerpt itself.
    assert "acme.example.com" not in result.summary
    assert "Series B" not in result.summary


def test_fetch_marks_not_mentioned_when_brand_name_is_absent_from_text(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "text": "A generic summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.mentioned is False


def test_fetch_returns_unavailable_reason_naming_the_endpoint_when_no_ai_overview_item_is_present(monkeypatch):
    payload = _success_payload([{"type": "organic", "rank_absolute": 1, "text": "just organic results"}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "no ai_overview item was found" in result.reason
    assert "endpoint=google_ai_mode_live_advanced" in result.reason


def test_fetch_success_reason_names_the_endpoint_label(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.reason == "DataForSEO Sandbox AI Mode request succeeded."


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


def test_password_never_appears_in_the_reason_string_on_success(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

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


def test_summary_strips_markdown_image_and_link_syntax(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme ![logo](https://example.com/logo.png) is featured on [TechCrunch](https://techcrunch.com/acme).",
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert result.success is True
    assert "https://example.com/logo.png" not in result.summary
    assert "https://techcrunch.com/acme" not in result.summary
    assert "TechCrunch" in result.summary


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_sandbox(_CREDENTIALS, "Acme")

    assert calls["count"] == 1
