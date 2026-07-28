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
    # ConnectTimeout is retryable (fix/common-crawl-index-retry); sleep is
    # mocked so this exhausts all 3 attempts without a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)

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
    assert seen_headers[0] == {
        "User-Agent": "Custom-UA/1.0",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }
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
    # ConnectTimeout is retryable (fix/common-crawl-index-retry); sleep is
    # mocked so this exhausts all 3 attempts without a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)

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
    # ConnectError is a retryable httpx.TransportError (see
    # fix/common-crawl-index-retry), so this now exhausts retries on
    # every query variant (fix/common-crawl-index-query-fallback) — 3
    # attempts x 3 variants. Sleep is mocked so the test doesn't wait.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)

    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 9
    assert "error_type=ConnectError" in failure_records[0].message
    assert "Name or service not known" in failure_records[0].message
    assert "query_variant=default-filtered" in failure_records[0].message


def test_search_logs_read_timeout_distinctly(monkeypatch, caplog):
    # ReadTimeout is also a retryable httpx.TransportError.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)

    def raise_read_timeout(url, **kwargs):
        raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_read_timeout)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 9
    assert "error_type=ReadTimeout" in failure_records[0].message
    assert "error_type=ConnectError" not in failure_records[0].message


def test_search_logs_status_code_and_body_preview_on_non_200(monkeypatch, caplog):
    # 500 is deliberately not one of the retryable statuses
    # (502/503/504 — see fix/common-crawl-index-retry), so this stays a
    # single-attempt scenario, matching this test's original intent of
    # checking the non-200 log line's shape rather than retry behavior.
    def fake_500(url, **kwargs):
        return httpx.Response(500, text="Service Unavailable", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_500)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    non_200_records = [r for r in caplog.records if "non-200" in r.message]
    assert len(non_200_records) == 1
    assert "status=500" in non_200_records[0].message
    assert "body_preview=Service Unavailable" in non_200_records[0].message


def test_search_body_preview_is_truncated_to_200_chars(monkeypatch, caplog):
    huge_body = "x" * 5000

    def fake_500(url, **kwargs):
        return httpx.Response(500, text=huge_body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_500)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    non_200_records = [r for r in caplog.records if "non-200" in r.message]
    assert len(non_200_records) == 1
    # Truncated preview (200 chars + "...") is far shorter than the huge body.
    assert len(non_200_records[0].message) < 400
    assert huge_body not in non_200_records[0].message


def test_search_logs_never_contain_html_or_warc_body(monkeypatch, caplog):
    body_with_html = "<html><body>should not leak into logs</body></html>" + "WARC/1.0 " * 20

    def fake_500(url, **kwargs):
        return httpx.Response(500, text=body_with_html, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_500)

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
    # ConnectError is retryable (fix/common-crawl-index-retry), so this
    # now runs all 3 attempts — sleep is mocked to avoid a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)

    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        resolve_common_crawl_index(_LATEST_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 3
    assert "error_type=ConnectError" in failure_records[0].message
    assert "Connection refused" in failure_records[0].message





# --- retry -------------------------------------------------------------------
# Added 2026-07-29 (fix/common-crawl-index-retry) — a Render deployment
# showed httpx.RemoteProtocolError ("Server disconnected without sending a
# response"), an abrupt-disconnect failure that happens instantly and is
# unaffected by COMMON_CRAWL_TIMEOUT_SECONDS. These tests lock in that such
# transient failures are retried (up to 3 attempts total) before falling
# back to the existing "unavailable" behavior, and that sleeping between
# retries never actually delays the test suite (time.sleep is mocked).


def _patch_sleep(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    return sleep_calls


def test_search_retries_on_remote_protocol_error_then_succeeds(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=httpx.Request("GET", url)
            )
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    assert calls["count"] == 2
    assert sleep_calls == [0.5]


def test_search_retries_on_read_timeout_then_succeeds(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert calls["count"] == 2


def test_search_retries_on_connect_error_then_succeeds(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("Name or service not known", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert calls["count"] == 2


def test_search_exhausts_retries_after_three_remote_protocol_errors(monkeypatch):
    # With query-variant fallback (fix/common-crawl-index-query-fallback),
    # a persistent RemoteProtocolError exhausts retries on every query
    # variant in turn (3 variants x 3 attempts = 9 calls) before finally
    # returning unavailable — see
    # test_search_all_query_variants_fail_and_log_final_failure for the
    # dedicated "all variants failed" logging assertions.
    sleep_calls = _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "network or timeout" in result.reason
    assert calls["count"] == 9
    assert sleep_calls == [0.5, 1.0, 0.5, 1.0, 0.5, 1.0]


def test_search_does_not_retry_on_http_400(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(400, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "400" in result.reason
    assert calls["count"] == 1


def test_search_does_not_retry_on_http_404(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert calls["count"] == 1


def test_search_retries_on_503_then_succeeds(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="Service Unavailable", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert calls["count"] == 2


def test_search_retries_on_502_and_504(monkeypatch):
    for status in (502, 504):
        _patch_sleep(monkeypatch)
        body = _cdxj_line(url="https://cybozu.co.jp/")
        calls = {"count": 0}

        def fake_get(url, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(status, text="gateway error", request=httpx.Request("GET", url))
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))

        monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

        assert result.status == "real"
        assert calls["count"] == 2


def test_search_logs_attempt_retrying_and_exhausted_messages(monkeypatch, caplog):
    _patch_sleep(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    messages = [r.message for r in caplog.records]
    assert any("attempt=1/3" in m and "request start" in m for m in messages)
    assert any("attempt=2/3" in m and "request start" in m for m in messages)
    assert any("attempt=3/3" in m and "request start" in m for m in messages)
    assert any("request retrying" in m and "next_attempt=2/3" in m and "delay=0.5" in m for m in messages)
    assert any("request retrying" in m and "next_attempt=3/3" in m and "delay=1.0" in m for m in messages)
    assert any(
        "request exhausted retries" in m and "attempts=3" in m and "last_error_type=RemoteProtocolError" in m
        for m in messages
    )


def test_search_logs_success_message_when_a_retry_succeeds(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    success_records = [r for r in caplog.records if "request succeeded" in r.message and "attempt=" in r.message]
    assert len(success_records) == 1
    assert "attempt=2/3" in success_records[0].message
    assert "candidates=1" in success_records[0].message


def test_search_retry_never_sleeps_more_than_1_5_seconds_per_query_variant(monkeypatch):
    # Each query variant still caps its own retry sleep at 0.5+1.0=1.5s;
    # with 3 variants (fix/common-crawl-index-query-fallback) a
    # persistent failure sleeps at most 3x1.5=4.5s in total, never more.
    sleep_calls = _patch_sleep(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert sum(sleep_calls) <= 4.5
    assert all(delay <= 1.0 for delay in sleep_calls)


def test_search_retry_does_not_change_reason_shown_to_ui(monkeypatch):
    _patch_sleep(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # The UI-facing reason (classified into Japanese by
    # app/lib/meta-label.ts) is unchanged by adding retry — still the same
    # "network or timeout error" reason as before this task.
    assert result.reason == "Common Crawl Index API request failed due to a network or timeout error."


# --- query-variant fallback ----------------------------------------------------
# Added 2026-07-29 (fix/common-crawl-index-query-fallback) — Render logs showed
# the standard (filtered) query exhausting all 3 retries with
# httpx.RemoteProtocolError even after fix/common-crawl-index-retry, meaning
# retrying the *same* query shape wasn't enough. These tests lock in that a
# persistent transport failure (or retryable non-200) falls back to a simpler
# query, and then a "www."-prefixed query, before finally giving up.


def test_search_falls_back_to_unfiltered_query_after_remote_protocol_error(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_params = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        seen_params.append(params)
        has_filter = any(k == "filter" for k, _ in params)
        # First query variant (has "filter") always fails; second variant
        # (no "filter" key at all) succeeds immediately.
        if has_filter:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=httpx.Request("GET", url)
            )
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # First variant (default-filtered) exhausted 3 attempts, then the
    # second variant (default-unfiltered) succeeded on its first attempt.
    assert len(seen_params) == 4
    assert sleep_calls == [0.5, 1.0]


def test_search_falls_back_to_unfiltered_query_after_read_timeout(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_falls_back_to_unfiltered_query_after_503(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            return httpx.Response(503, text="Service Unavailable", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_falls_back_through_www_variant_when_first_two_fail(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://www.cybozu.co.jp/")
    seen_urls = []

    def fake_get(url, **kwargs):
        params = dict(kwargs.get("params"))
        seen_urls.append(params.get("url"))
        if params.get("url") == "www.cybozu.co.jp/*":
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    assert "www.cybozu.co.jp/*" in seen_urls
    # Two prior variants (default-filtered, default-unfiltered) each
    # exhausted 3 attempts before the www variant was tried.
    assert seen_urls.count("cybozu.co.jp/*") == 6
    assert seen_urls.count("www.cybozu.co.jp/*") == 1


def test_search_all_query_variants_fail_and_log_final_failure(monkeypatch, caplog):
    _patch_sleep(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert result.reason == "Common Crawl Index API request failed due to a network or timeout error."

    messages = [r.message for r in caplog.records]
    fallback_records = [m for m in messages if "query fallback" in m]
    assert len(fallback_records) == 2
    assert any("from=default-filtered" in m and "to=default-unfiltered" in m for m in fallback_records)
    assert any("from=default-unfiltered" in m and "to=www-unfiltered" in m for m in fallback_records)
    assert all("reason=RemoteProtocolError" in m for m in fallback_records)

    final_records = [m for m in messages if "all query variants failed" in m]
    assert len(final_records) == 1
    assert "variants=3" in final_records[0]
    assert "last_error_type=RemoteProtocolError" in final_records[0]


def test_search_does_not_fall_back_to_next_query_on_http_400(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(400, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "400" in result.reason
    # Only the first query variant's first attempt — no retry, no fallback.
    assert calls["count"] == 1


def test_search_does_not_fall_back_to_next_query_on_http_404(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert calls["count"] == 1


def test_search_does_not_fall_back_to_next_query_on_zero_candidates(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason
    # Only the first query variant — a successful-but-empty result does
    # not fall back to a broader/simpler query in this MVP.
    assert calls["count"] == 1


def test_search_logs_query_variant_in_request_start(monkeypatch, caplog):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    assert "query_variant=default-filtered" in start_records[0]


def test_search_logs_query_variant_in_success_message_after_fallback(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    success_records = [r.message for r in caplog.records if "request succeeded" in r.message]
    assert len(success_records) == 1
    assert "query_variant=default-unfiltered" in success_records[0]
    assert "attempt=1/3" in success_records[0]
    assert "candidates=1" in success_records[0]


def test_search_www_variant_is_skipped_when_domain_already_has_www(monkeypatch):
    calls = {"count": 0}
    seen_urls = []

    def fake_get(url, **kwargs):
        calls["count"] += 1
        params = dict(kwargs.get("params"))
        seen_urls.append(params.get("url"))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)
    _patch_sleep(monkeypatch)

    search_common_crawl_domain("www.cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # Only 2 variants (default-filtered, default-unfiltered) for a domain
    # that already starts with "www." — no doubled-up "www.www." variant.
    assert calls["count"] == 6
    assert all(u == "www.cybozu.co.jp/*" for u in seen_urls)


def test_search_query_fallback_does_not_change_candidate_parsing(monkeypatch):
    # Regression guard: candidate parsing behaves identically regardless
    # of which query variant produced the 200 response.
    _patch_sleep(monkeypatch)
    body = _cdxj_line(
        url="https://cybozu.co.jp/",
        timestamp="20260115000000",
        status="200",
        mime="text/html",
        digest="ABC123",
    )

    def fake_get(url, **kwargs):
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate = result.candidates[0]
    assert candidate.url == "https://cybozu.co.jp/"
    assert candidate.timestamp == "20260115000000"
    assert candidate.status == 200
    assert candidate.mime == "text/html"
    assert candidate.digest == "ABC123"
    assert candidate.source == "common_crawl"


# --- retry (collinfo.json / resolve_common_crawl_index) -----------------------


def test_fetch_latest_index_retries_on_remote_protocol_error_then_succeeds(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-08"
    assert calls["count"] == 2
    assert sleep_calls == [0.5]


def test_fetch_latest_index_exhausts_retries_and_fails_safely(monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    assert "network or timeout" in resolution.reason
    assert calls["count"] == 3
    assert sleep_calls == [0.5, 1.0]


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


# --- explicit request headers ---------------------------------------------------
# Added 2026-07-29 (fix/common-crawl-index-request-headers) — Render logs showed
# *every* query variant (default-filtered/default-unfiltered/www-unfiltered)
# failing with httpx.RemoteProtocolError even with retry and query fallback
# already in place. As a low-risk next step (before trust_env=False or a
# different HTTP client), Index API requests now send an explicit User-Agent,
# Accept, and "Connection: close" header — in case the disconnect is a
# keep-alive/connection-reuse interaction with Render's networking.


def test_search_sends_user_agent_header(monkeypatch):
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert seen_headers[0]["User-Agent"] == "AI-Visibility-Platform-MVP"


def test_search_sends_accept_header(monkeypatch):
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert "application/json" in seen_headers[0]["Accept"]


def test_search_sends_connection_close_header(monkeypatch):
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert seen_headers[0]["Connection"] == "close"


def test_search_uses_common_crawl_user_agent_setting(monkeypatch):
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    settings = CommonCrawlSettings(
        enabled=True,
        index="CC-MAIN-2026-08",
        max_results=5,
        timeout_seconds=10.0,
        user_agent="My-Custom-Agent/2.0",
    )
    search_common_crawl_domain("cybozu.co.jp", settings)

    assert seen_headers[0]["User-Agent"] == "My-Custom-Agent/2.0"


def test_fetch_latest_index_sends_the_same_headers(monkeypatch):
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolve_common_crawl_index(_LATEST_SETTINGS)

    assert seen_headers[0] == {
        "User-Agent": "AI-Visibility-Platform-MVP",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }


def test_search_headers_are_maintained_across_retries(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_headers = []
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        seen_headers.append(kwargs.get("headers"))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # 3 attempts for the first variant alone (before falling back).
    assert calls["count"] >= 3
    assert all(
        h
        == {
            "User-Agent": "AI-Visibility-Platform-MVP",
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "Connection": "close",
        }
        for h in seen_headers
    )


def test_search_headers_are_maintained_across_query_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    # Headers are identical across the failing variant and the
    # fallback variant that eventually succeeds.
    expected_headers = {
        "User-Agent": "AI-Visibility-Platform-MVP",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }
    assert all(h == expected_headers for h in seen_headers)


def test_search_second_attempt_success_behavior_unchanged_by_headers(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    assert calls["count"] == 2


def test_search_logs_headers_summary_in_request_start(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    assert "user_agent=AI-Visibility-Platform-MVP" in start_records[0]
    assert "accept=application/json" in start_records[0]
    assert "connection=close" in start_records[0]


def test_fetch_latest_index_logs_headers_summary_in_request_start(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        resolve_common_crawl_index(_LATEST_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    assert "user_agent=AI-Visibility-Platform-MVP" in start_records[0]
    assert "accept=application/json" in start_records[0]
    assert "connection=close" in start_records[0]


def test_search_logs_never_contain_raw_header_dict_or_secret_looking_values(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    messages = " ".join(r.message for r in caplog.records)
    # Only the compact key=value fields should appear — never a raw dict
    # repr (which would look like "{'User-Agent': ...}"), and no
    # Authorization/token/api-key-shaped header (there is none to leak,
    # since Common Crawl requires no authentication).
    assert "{'User-Agent'" not in messages
    assert "Authorization" not in messages
    assert "api_key" not in messages.lower()
    assert "token" not in messages.lower()


def test_search_headers_do_not_affect_candidate_parsing(monkeypatch):
    # Regression guard: adding explicit headers must not change how a
    # successful response's candidates are parsed.
    body = _cdxj_line(
        url="https://cybozu.co.jp/",
        timestamp="20260115000000",
        status="200",
        mime="text/html",
        digest="ABC123",
    )

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate = result.candidates[0]
    assert candidate.url == "https://cybozu.co.jp/"
    assert candidate.timestamp == "20260115000000"
    assert candidate.status == 200
    assert candidate.mime == "text/html"
    assert candidate.digest == "ABC123"
    assert candidate.source == "common_crawl"


def test_search_headers_do_not_change_reason_shown_to_ui(monkeypatch):
    _patch_sleep(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert result.reason == "Common Crawl Index API request failed due to a network or timeout error."
