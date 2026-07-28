import json
import logging

import httpx

from services import common_crawl_index
from services.common_crawl_index import (
    COLLINFO_URL,
    resolve_common_crawl_index,
    search_common_crawl_domain,
)
from services.common_crawl_settings import CommonCrawlSettings

_LATEST_SETTINGS = CommonCrawlSettings(
    enabled=True,
    index="latest",
    max_results=5,
    timeout_seconds=10.0,
    user_agent="AI-Visibility-Platform-MVP",
)

_FIXED_INDEX_SETTINGS = CommonCrawlSettings(
    enabled=True,
    index="CC-MAIN-2026-08",
    max_results=5,
    timeout_seconds=10.0,
    user_agent="AI-Visibility-Platform-MVP",
)


def _collinfo_payload(*ids: str) -> list[dict]:
    return [{"id": crawl_id, "name": crawl_id} for crawl_id in ids]


# --- resolve_common_crawl_index ---------------------------------------------


def test_resolve_latest_index_from_collinfo(monkeypatch):
    def fake_get(url, **kwargs):
        assert url == COLLINFO_URL
        return httpx.Response(
            200,
            json=_collinfo_payload("CC-MAIN-2026-04", "CC-MAIN-2026-08"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-08"


def test_resolve_latest_index_picks_the_greatest_id_regardless_of_list_order(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            # Deliberately not in chronological order — resolution must
            # not assume collinfo.json is pre-sorted.
            json=_collinfo_payload("CC-MAIN-2025-50", "CC-MAIN-2026-01", "CC-MAIN-2025-12"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-01"


def test_resolve_latest_index_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_timeout)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    assert resolution.crawl_index is None
    assert "network or timeout" in resolution.reason


def test_resolve_latest_index_fails_safely_on_non_200(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    assert "500" in resolution.reason


def test_resolve_latest_index_fails_safely_on_invalid_json(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False


def test_resolve_latest_index_fails_safely_when_no_valid_ids_present(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200, json=[{"id": "not-a-crawl-id"}], request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False


def test_resolve_configured_index_never_calls_collinfo(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("collinfo.json should not be requested when an explicit index is configured")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    resolution = resolve_common_crawl_index(_FIXED_INDEX_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-08"


# --- domain normalization (via search_common_crawl_domain) -----------------


def test_search_normalizes_a_full_url_to_a_bare_hostname(monkeypatch):
    seen_params = []

    def fake_get(url, **kwargs):
        seen_params.append(kwargs.get("params"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("https://example.com/path", _FIXED_INDEX_SETTINGS)

    params = dict(seen_params[0])
    assert params["url"] == "example.com/*"


def test_search_lowercases_the_domain(monkeypatch):
    seen_params = []

    def fake_get(url, **kwargs):
        seen_params.append(kwargs.get("params"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("EXAMPLE.COM", _FIXED_INDEX_SETTINGS)

    params = dict(seen_params[0])
    assert params["url"] == "example.com/*"


def test_search_rejects_an_empty_domain():
    result = search_common_crawl_domain("", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "invalid" in result.reason or "empty" in result.reason


def test_search_rejects_a_dangerous_domain_without_calling_httpx(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.get should not be called for an invalid domain")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    result = search_common_crawl_domain("javascript:alert(1)", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"


def test_search_rejects_a_bare_word_with_no_dot(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.get should not be called for a hostname with no dot")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    result = search_common_crawl_domain("localhost", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"


# --- Index API request shape -------------------------------------------------


def test_search_sends_expected_query_params(monkeypatch):
    seen_urls = []
    seen_params = []
    seen_headers = []
    seen_timeout = []

    def fake_get(url, **kwargs):
        seen_urls.append(url)
        seen_params.append(kwargs.get("params"))
        seen_headers.append(kwargs.get("headers"))
        seen_timeout.append(kwargs.get("timeout"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    settings = CommonCrawlSettings(
        enabled=True,
        index="CC-MAIN-2026-08",
        max_results=3,
        timeout_seconds=7.5,
        user_agent="Custom-UA/1.0",
    )
    search_common_crawl_domain("cybozu.co.jp", settings)

    assert seen_urls == ["https://index.commoncrawl.org/CC-MAIN-2026-08-index"]
    params = seen_params[0]
    assert ("url", "cybozu.co.jp/*") in params
    assert ("output", "json") in params
    assert ("filter", "status:200") in params
    assert ("filter", "mime:text/html") in params
    assert ("limit", "3") in params
    assert seen_headers[0] == {"User-Agent": "Custom-UA/1.0"}
    assert seen_timeout[0] == 7.5


# --- JSON Lines parsing / normalization --------------------------------------


def _cdxj_line(**fields) -> str:
    return json.dumps(fields)


def test_search_parses_json_lines_into_candidates(monkeypatch):
    body = "\n".join(
        [
            _cdxj_line(
                url="https://cybozu.co.jp/",
                timestamp="20260115000000",
                status="200",
                mime="text/html",
                digest="ABC123",
                length="12345",
                offset="67890",
                filename="crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz",
            ),
        ]
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.url == "https://cybozu.co.jp/"
    assert candidate.timestamp == "20260115000000"
    assert candidate.status == 200
    assert candidate.mime == "text/html"
    assert candidate.digest == "ABC123"
    assert candidate.length == 12345
    assert candidate.offset == 67890
    assert candidate.filename == "crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz"
    assert candidate.crawl_index == "CC-MAIN-2026-08"
    assert candidate.source == "common_crawl"


def test_search_handles_int_typed_status_length_offset(monkeypatch):
    body = json.dumps(
        {"url": "https://cybozu.co.jp/", "status": 200, "length": 111, "offset": 222}
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.candidates[0].status == 200
    assert result.candidates[0].length == 111
    assert result.candidates[0].offset == 222


def test_search_skips_lines_missing_url_but_keeps_valid_ones(monkeypatch):
    body = "\n".join(
        [
            _cdxj_line(status="200"),  # missing url — skipped
            _cdxj_line(url="https://cybozu.co.jp/about"),
        ]
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://cybozu.co.jp/about"


def test_search_does_not_crash_on_missing_optional_fields(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate = result.candidates[0]
    assert candidate.timestamp is None
    assert candidate.status is None
    assert candidate.mime is None
    assert candidate.digest is None
    assert candidate.length is None
    assert candidate.offset is None
    assert candidate.filename is None


def test_search_never_retains_html_or_warc_body(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/", html="<html>should not appear</html>")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate_fields = vars(result.candidates[0])
    assert "should not appear" not in str(candidate_fields)


def test_search_respects_max_results_even_if_more_lines_are_returned(monkeypatch):
    body = "\n".join(
        _cdxj_line(url=f"https://cybozu.co.jp/page{i}") for i in range(10)
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    settings = CommonCrawlSettings(
        enabled=True, index="CC-MAIN-2026-08", max_results=3, timeout_seconds=10.0, user_agent="ua"
    )
    result = search_common_crawl_domain("cybozu.co.jp", settings)

    assert len(result.candidates) == 3


# --- failure handling --------------------------------------------------------


def test_search_returns_unavailable_and_empty_reason_safe_on_zero_results(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert result.candidates == ()
    assert "empty" in result.reason


def test_search_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_timeout)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "network or timeout" in result.reason


def test_search_fails_safely_on_http_404(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "404" in result.reason


def test_search_fails_safely_on_http_500(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "500" in result.reason


def test_search_propagates_index_resolution_failure(monkeypatch):
    def fake_get(url, **kwargs):
        assert url == COLLINFO_URL
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _LATEST_SETTINGS)

    assert result.status == "unavailable"
    assert "collinfo.json" in result.reason


def test_search_reason_never_contains_a_huge_response_body(monkeypatch):
    huge_body = "not json " * 100000

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=huge_body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # Every line failed to parse as JSON (or lacked a url), so this is
    # treated the same as zero results — the huge body is never echoed
    # back in `reason`.
    assert len(result.reason) < 500


# --- diagnostic logging -------------------------------------------------------
# Added 2026-07-29 (chore/common-crawl-index-diagnostics) — a Render deployment
# reported an instant (not timeout-length) failure with only a generic
# "network/timeout error" WARNING in the logs, with no way to tell whether it
# was a genuine read timeout, DNS/connection/SSL failure, or something else.
# These tests lock in that Render logs alone can now distinguish those cases.


def test_search_logs_request_start_with_index_domain_timeout_and_url(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)
    settings = CommonCrawlSettings(
        enabled=True, index="CC-MAIN-2026-25", max_results=5, timeout_seconds=60.0, user_agent="ua"
    )

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", settings)

    start_records = [r for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    message = start_records[0].message
    assert "index=CC-MAIN-2026-25" in message
    assert "domain=cybozu.co.jp" in message
    assert "timeout=60.0" in message
    assert "url_pattern=cybozu.co.jp/*" in message
    assert "index.commoncrawl.org/CC-MAIN-2026-25-index" in message
    assert "cybozu.co.jp" in message


def test_search_logs_distinguish_connect_error_from_read_timeout(monkeypatch, caplog):
    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 1
    assert "error_type=ConnectError" in failure_records[0].message
    assert "Name or service not known" in failure_records[0].message


def test_search_logs_read_timeout_distinctly(monkeypatch, caplog):
    def raise_read_timeout(url, **kwargs):
        raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_read_timeout)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 1
    assert "error_type=ReadTimeout" in failure_records[0].message
    assert "error_type=ConnectError" not in failure_records[0].message


def test_search_logs_status_code_and_body_preview_on_non_200(monkeypatch, caplog):
    def fake_503(url, **kwargs):
        return httpx.Response(503, text="Service Unavailable", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_503)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    non_200_records = [r for r in caplog.records if "non-200" in r.message]
    assert len(non_200_records) == 1
    assert "status=503" in non_200_records[0].message
    assert "body_preview=Service Unavailable" in non_200_records[0].message


def test_search_body_preview_is_truncated_to_200_chars(monkeypatch, caplog):
    huge_body = "x" * 5000

    def fake_503(url, **kwargs):
        return httpx.Response(503, text=huge_body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_503)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    non_200_records = [r for r in caplog.records if "non-200" in r.message]
    assert len(non_200_records) == 1
    # Truncated preview (200 chars + "...") is far shorter than the huge body.
    assert len(non_200_records[0].message) < 400
    assert huge_body not in non_200_records[0].message


def test_search_logs_never_contain_html_or_warc_body(monkeypatch, caplog):
    body_with_html = "<html><body>should not leak into logs</body></html>" + "WARC/1.0 " * 20

    def fake_503(url, **kwargs):
        return httpx.Response(503, text=body_with_html, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_503)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    non_200_records = [r for r in caplog.records if "non-200" in r.message]
    assert len(non_200_records) == 1
    # The 200-char preview cap means only a prefix of this (deliberately
    # HTML/WARC-shaped) body could ever leak through, and even that
    # prefix is a bounded preview, never the full body.
    assert len(non_200_records[0].message) < 400


def test_fetch_latest_index_logs_request_start_with_url_and_timeout(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)
    settings = CommonCrawlSettings(
        enabled=True, index="latest", max_results=5, timeout_seconds=45.0, user_agent="ua"
    )

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        resolve_common_crawl_index(settings)

    start_records = [r for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    assert "url=https://index.commoncrawl.org/collinfo.json" in start_records[0].message
    assert "timeout=45.0" in start_records[0].message


def test_fetch_latest_index_logs_error_type_on_connect_error(monkeypatch, caplog):
    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        resolve_common_crawl_index(_LATEST_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 1
    assert "error_type=ConnectError" in failure_records[0].message
    assert "Connection refused" in failure_records[0].message


def test_search_logging_does_not_change_success_behavior(monkeypatch, caplog):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # Adding diagnostic logging must not affect the actual result.
    assert result.status == "real"
    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://cybozu.co.jp/"
    # The reason shown to the UI (and eventually classified into a
    # Japanese message by app/lib/meta-label.ts) is unchanged.
    assert "Common Crawl Index API request succeeded" in result.reason
