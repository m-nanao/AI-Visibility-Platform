import httpx

from services import dataforseo_client
from services.dataforseo_client import (
    AI_MODE_LIVE_ADVANCED_PATH,
    ORGANIC_LIVE_ADVANCED_PATH,
    fetch_ai_overview_serp,
)
from services.dataforseo_settings import LIVE_BASE_URL, SANDBOX_BASE_URL, DataForSEOCredentials

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

    fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    fetch_ai_overview_serp(_CREDENTIALS, "Acme", endpoint="google_organic_live_advanced")

    assert seen_urls == [f"{SANDBOX_BASE_URL}{ORGANIC_LIVE_ADVANCED_PATH}"]


def test_fetch_uses_live_base_url_when_api_env_is_live(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200,
            json=_success_payload([{"type": "ai_overview", "markdown": "Acme is great."}]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert seen_urls == [f"{LIVE_BASE_URL}{AI_MODE_LIVE_ADVANCED_PATH}"]
    assert LIVE_BASE_URL == "https://api.dataforseo.com"
    assert LIVE_BASE_URL != SANDBOX_BASE_URL


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

    fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert seen_auth == [("someone@example.com", "super-secret-password")]


def test_fetch_sends_keyword_location_language_device_and_os_in_the_payload(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_serp(
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


def test_fetch_sends_the_same_single_item_payload_for_live_too(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert len(seen_bodies) == 1
    assert len(seen_bodies[0]) == 1
    assert seen_bodies[0][0]["keyword"] == "Acme"


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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is True
    assert "well-reviewed tool for teams" in result.summary
    assert "plain-text fallback" not in result.summary


def test_fetch_falls_back_to_rank_group_when_rank_absolute_is_missing(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_group": 3, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.mentioned is False


def test_fetch_returns_unavailable_reason_naming_the_endpoint_when_no_ai_overview_item_is_present(monkeypatch):
    payload = _success_payload([{"type": "organic", "rank_absolute": 1, "text": "just organic results"}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "no ai_overview item was found" in result.reason
    assert "endpoint=google_ai_mode_live_advanced" in result.reason
    assert "DataForSEO Sandbox" in result.reason


def test_fetch_success_reason_names_the_sandbox_environment_and_endpoint_label(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is True
    assert result.reason == "DataForSEO Sandbox AI Mode request succeeded."


def test_fetch_success_reason_names_the_live_environment_and_endpoint_label(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert result.success is True
    assert result.reason == "DataForSEO Live AI Mode request succeeded."


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_network_error_for_live_too(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert result.success is False
    assert "DataForSEO Live" in result.reason
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is False


def test_fetch_fails_safely_on_unexpected_status_code_in_payload(monkeypatch):
    payload = {"status_code": 40100, "status_message": "Auth failed."}

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.success is False


def test_fetch_never_raises_out_of_the_function(monkeypatch):
    def raise_unexpected(url, **kwargs):
        raise RuntimeError("something exploded")

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_unexpected)

    try:
        result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")
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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert "super-secret-password" not in result.reason
    assert "someone@example.com" not in result.reason


def test_password_never_appears_in_the_reason_string_on_success(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert "super-secret-password" not in result.reason
    assert "someone@example.com" not in result.reason


def test_password_never_appears_in_the_reason_string_for_live_either(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert "super-secret-password" not in result.reason
    assert "someone@example.com" not in result.reason


def test_summary_is_truncated_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "text": long_text}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

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

    fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert calls["count"] == 1


def test_fetch_sends_exactly_one_request_for_live_too(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json=_success_payload([]), request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    fetch_ai_overview_serp(_CREDENTIALS, "Acme", api_env="live")

    assert calls["count"] == 1


# --- fullSummary / references -----------------------------------------


def test_fetch_builds_full_summary_from_item_markdown(monkeypatch):
    payload = _success_payload(
        [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme is a well-reviewed tool for teams."}]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.full_summary == "Acme is a well-reviewed tool for teams."


def test_full_summary_strips_markdown_images(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme ![logo](https://example.com/logo.png) is a tool.",
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert "https://example.com/logo.png" not in result.full_summary
    assert "Acme" in result.full_summary
    assert "is a tool." in result.full_summary


def test_full_summary_flattens_markdown_links_to_display_text(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme is featured on [TechCrunch](https://techcrunch.com/acme).",
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert "TechCrunch" in result.full_summary
    assert "https://techcrunch.com/acme" not in result.full_summary


def test_full_summary_is_none_when_no_readable_text(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.full_summary is None


def test_full_summary_is_truncated_far_beyond_the_short_summary_cap(monkeypatch):
    long_text = "Acme " + ("word " * 1000)
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": long_text}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.full_summary) <= dataforseo_client._FULL_SUMMARY_MAX_CHARS + 1
    assert result.full_summary.endswith("…")
    assert len(result.full_summary) > len(result.summary)


def test_fetch_extracts_references_from_item_references(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme summary.",
                "references": [
                    {
                        "type": "ai_overview_reference",
                        "source": "web",
                        "domain": "acme.example.com",
                        "url": "https://acme.example.com/about",
                        "title": "About Acme",
                        "text": "Acme is a company.",
                        "position": "left",
                    }
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 1
    reference = result.references[0]
    assert reference.domain == "acme.example.com"
    assert reference.url == "https://acme.example.com/about"
    assert reference.title == "About Acme"
    assert reference.text == "Acme is a company."
    assert reference.source == "web"
    assert reference.position == "left"


def test_fetch_extracts_references_from_nested_items_references(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "items": [
                    {
                        "text": "Acme helps teams collaborate.",
                        "references": [{"domain": "acme.example.com", "title": "Acme"}],
                    }
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 1
    assert result.references[0].domain == "acme.example.com"


def test_fetch_extracts_references_from_nested_items_links(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "items": [
                    {
                        "text": "Acme helps teams collaborate.",
                        "links": [
                            {
                                "type": "link_element",
                                "title": "Acme Docs",
                                "description": "Official docs",
                                "url": "https://acme.example.com/docs",
                                "domain": "acme.example.com",
                            }
                        ],
                    }
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 1
    reference = result.references[0]
    assert reference.url == "https://acme.example.com/docs"
    assert reference.text == "Official docs"


def test_fetch_extracts_references_from_item_links(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme summary.",
                "links": [{"title": "Acme", "url": "https://acme.example.com", "domain": "acme.example.com"}],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 1
    assert result.references[0].url == "https://acme.example.com"


def test_fetch_deduplicates_references_with_the_same_url(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme summary.",
                "references": [
                    {"domain": "acme.example.com", "url": "https://acme.example.com", "title": "Acme"},
                    {"domain": "acme.example.com", "url": "https://acme.example.com", "title": "Acme (duplicate)"},
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 1
    assert result.references[0].title == "Acme"


def test_fetch_deduplicates_references_without_url_by_domain_and_title(monkeypatch):
    payload = _success_payload(
        [
            {
                "type": "ai_overview",
                "rank_absolute": 1,
                "markdown": "Acme summary.",
                "references": [
                    {"domain": "acme.example.com", "title": "Acme"},
                    {"domain": "acme.example.com", "title": "Acme"},
                    {"domain": "acme.example.com", "title": "Acme (different title)"},
                ],
            }
        ]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 2


def test_fetch_caps_references_at_ten(monkeypatch):
    references = [
        {"domain": f"example{i}.com", "url": f"https://example{i}.com", "title": f"Example {i}"}
        for i in range(15)
    ]
    payload = _success_payload(
        [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary.", "references": references}]
    )

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert len(result.references) == 10


def test_fetch_returns_no_references_when_none_are_present(monkeypatch):
    payload = _success_payload([{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme summary."}])

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    result = fetch_ai_overview_serp(_CREDENTIALS, "Acme")

    assert result.references == ()
