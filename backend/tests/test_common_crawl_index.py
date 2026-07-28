import io
import json
import logging
import urllib.error

import httpx
import pytest

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


@pytest.fixture(autouse=True)
def _no_real_urllib_calls(monkeypatch):
    """Safety net for the `urllib` transport mode (fix/common-crawl-index-
    urllib-fallback): no test should ever let `urllib.request.urlopen`
    reach the real network. A test that wants to exercise the `urllib`
    transport mode monkeypatches `common_crawl_index.urllib.request.urlopen`
    itself, which overrides this default. Any *other* test that
    accidentally exhausts the `default`/`no-env` httpx transports and
    falls through to `urllib` will hit this and fail fast with a clear
    error instead of hanging on a real network call.
    """

    def fail_if_called(request, timeout=None):
        raise AssertionError(
            "urllib.request.urlopen should not be reached unless a test explicitly mocks it"
        )

    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fail_if_called)


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
    # mocked so this exhausts all 3 attempts (across all 3 transport
    # modes — fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback) without a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)
    _patch_urllib_persistent_failure(monkeypatch)

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

    # The first variant tried is exact-domain-unfiltered (url=domain, no
    # "/*" wildcard) — domain normalization (scheme/path stripping)
    # applies before any variant is built.
    params = dict(seen_params[0])
    assert params["url"] == "example.com"


def test_search_lowercases_the_domain(monkeypatch):
    seen_params = []

    def fake_get(url, **kwargs):
        seen_params.append(kwargs.get("params"))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("EXAMPLE.COM", _FIXED_INDEX_SETTINGS)

    params = dict(seen_params[0])
    assert params["url"] == "example.com"


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

    # Every attempt hits the same base URL (only query params differ
    # between variants) — a 200-but-empty response from every variant
    # means exact-domain-unfiltered/exact-domain-filtered (both
    # allow_empty_fallback=True) fall through, and default-filtered
    # (allow_empty_fallback=False) terminates on its own empty result,
    # so exactly 3 calls are made (the 2 later wildcard variants are
    # never reached).
    assert seen_urls == ["https://index.commoncrawl.org/CC-MAIN-2026-08-index"] * 3
    assert seen_headers[0] == {
        "User-Agent": "Custom-UA/1.0",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }
    assert seen_timeout[0] == 7.5

    # 1st variant: exact-domain-unfiltered (url=domain, no wildcard, no filters).
    exact_unfiltered_params = seen_params[0]
    assert ("url", "cybozu.co.jp") in exact_unfiltered_params
    assert ("output", "json") in exact_unfiltered_params
    assert ("limit", "3") in exact_unfiltered_params
    assert not any(key == "filter" for key, _ in exact_unfiltered_params)

    # 2nd variant: exact-domain-filtered (url=domain, no wildcard, with filters).
    exact_filtered_params = seen_params[1]
    assert ("url", "cybozu.co.jp") in exact_filtered_params
    assert ("filter", "status:200") in exact_filtered_params
    assert ("filter", "mime:text/html") in exact_filtered_params
    assert ("limit", "3") in exact_filtered_params

    # 3rd variant: default-filtered (url=domain/*, with filters) — the
    # original wildcard query this test exercised before exact-domain
    # variants were added.
    default_filtered_params = seen_params[2]
    assert ("url", "cybozu.co.jp/*") in default_filtered_params
    assert ("output", "json") in default_filtered_params
    assert ("filter", "status:200") in default_filtered_params
    assert ("filter", "mime:text/html") in default_filtered_params
    assert ("limit", "3") in default_filtered_params


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
    # mocked so this exhausts every query variant across all 3 transport
    # modes without a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)
    _patch_urllib_persistent_failure(monkeypatch)

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
    # exact-domain-unfiltered/exact-domain-filtered fall through on their
    # own empty result; default-filtered (the first wildcard variant)
    # then terminates on its own empty result — 3 start records total.
    assert len(start_records) == 3
    message = start_records[-1].message
    assert "index=CC-MAIN-2026-25" in message
    assert "domain=cybozu.co.jp" in message
    assert "timeout=60.0" in message
    assert "url_pattern=cybozu.co.jp/*" in message
    assert "query_variant=default-filtered" in message
    assert "index.commoncrawl.org/CC-MAIN-2026-25-index" in message
    assert "cybozu.co.jp" in message


def test_search_logs_distinguish_connect_error_from_read_timeout(monkeypatch, caplog):
    # ConnectError is a retryable httpx.TransportError (see
    # fix/common-crawl-index-retry), so this now exhausts retries on
    # every query variant under every transport mode
    # (fix/common-crawl-index-query-fallback,
    # fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback,
    # fix/common-crawl-index-exact-domain-query) — 3 attempts x 5
    # variants x 3 transport modes. Sleep is mocked so the test doesn't
    # wait.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)
    _patch_urllib_persistent_failure(monkeypatch)

    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 45
    assert "error_type=ConnectError" in failure_records[0].message
    assert "Name or service not known" in failure_records[0].message
    assert "query_variant=exact-domain-unfiltered" in failure_records[0].message
    assert "transport_mode=default" in failure_records[0].message
    assert "transport_mode=urllib" in failure_records[-1].message
    assert "error_type=URLError" in failure_records[-1].message


def test_search_logs_read_timeout_distinctly(monkeypatch, caplog):
    # ReadTimeout is also a retryable httpx.TransportError.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)
    _patch_urllib_persistent_failure(monkeypatch)

    def raise_read_timeout(url, **kwargs):
        raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_read_timeout)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 45
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
    # now runs all 3 attempts under all 3 transport modes
    # (fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback) — sleep is mocked to avoid
    # a real delay.
    monkeypatch.setattr(common_crawl_index.time, "sleep", lambda seconds: None)
    _patch_urllib_persistent_failure(monkeypatch)

    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", raise_connect_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        resolve_common_crawl_index(_LATEST_SETTINGS)

    failure_records = [r for r in caplog.records if "request failed" in r.message]
    assert len(failure_records) == 9
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


def _patch_urllib_persistent_failure(monkeypatch, message="disconnected"):
    """Makes the `urllib` transport mode fail on every call with a
    persistent `OSError`-derived error (mirroring a persistent
    `httpx.RemoteProtocolError` fake on the httpx transports) — for
    tests simulating total exhaustion across all `_TRANSPORT_MODES`
    (`default`/`no-env`/`urllib`).
    """

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError(message)

    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)


class _FakeUrllibHeaders:
    """Minimal stand-in for the `email.message.Message`-like `.headers`
    object a real `http.client.HTTPResponse`/`urllib.error.HTTPError`
    exposes — `_urllib_get()` only ever calls `.get_content_charset()`
    on it, and always falls back to utf-8 when it returns `None`.
    """

    def get_content_charset(self):
        return None


class _FakeUrllibResponse:
    """Stand-in for what `urllib.request.urlopen()` returns on success —
    supports the context-manager protocol plus `.status`/`.read()`/
    `.headers`, which is all `_urllib_get()` reads.
    """

    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = _FakeUrllibHeaders()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_http_error(request_url: str, code: int, body: str) -> urllib.error.HTTPError:
    """Builds a `urllib.error.HTTPError` shaped like what a real non-2xx
    response would raise — `_urllib_get()` reads `.code` and `.read()`
    from it (via `exc.headers`, which is `None` here, exercised
    separately from the success-path `_FakeUrllibHeaders`).
    """
    return urllib.error.HTTPError(request_url, code, "", None, io.BytesIO(body.encode("utf-8")))


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
    # With query-variant fallback (fix/common-crawl-index-query-fallback,
    # fix/common-crawl-index-exact-domain-query) and transport-mode
    # fallback (fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback), a persistent failure
    # exhausts retries on every query variant under every transport mode
    # (5 variants x 3 attempts x 3 transport modes = 45 calls) before
    # finally returning unavailable — see
    # test_search_all_query_variants_fail_and_log_final_failure for the
    # dedicated "all variants/transports failed" logging assertions.
    sleep_calls = _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)
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
    # 2 httpx transport modes (default, no-env) x 5 variants x 3 attempts.
    assert calls["count"] == 30
    assert sleep_calls == [0.5, 1.0, 0.5, 1.0, 0.5, 1.0, 0.5, 1.0, 0.5, 1.0] * 3


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
    _patch_urllib_persistent_failure(monkeypatch)

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
    # with 5 variants (fix/common-crawl-index-query-fallback,
    # fix/common-crawl-index-exact-domain-query) and 3 transport modes
    # (fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback), a persistent failure
    # sleeps at most 5x1.5x3=22.5s in total, never more.
    sleep_calls = _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert sum(sleep_calls) <= 22.5
    assert all(delay <= 1.0 for delay in sleep_calls)


def test_search_retry_does_not_change_reason_shown_to_ui(monkeypatch):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

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
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        # Every variant fails except default-unfiltered (url=domain/*,
        # no status/mime filters) — the first two ("exact", no wildcard)
        # variants and default-filtered all fail, then default-unfiltered
        # succeeds immediately.
        if url_param == "cybozu.co.jp/*" and not has_filter:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # exact-domain-unfiltered, exact-domain-filtered, and default-filtered
    # each exhaust 3 attempts (9 calls total), then default-unfiltered
    # succeeds on its first attempt.
    assert len(seen_params) == 10
    assert sleep_calls == [0.5, 1.0, 0.5, 1.0, 0.5, 1.0]


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
    # A persistent failure exhausts every query variant under all 3
    # transport modes (fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback), so "query fallback"/"all
    # query variants failed" each appear 3 times (once per transport
    # mode) before the final "all transports failed". The two httpx
    # modes fail with RemoteProtocolError; the urllib mode fails with
    # URLError (see _patch_urllib_persistent_failure).
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

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
    # 5 variants -> 4 fallback transitions per transport mode x 3 modes.
    assert len(fallback_records) == 12
    assert any("from=exact-domain-unfiltered" in m and "to=exact-domain-filtered" in m for m in fallback_records)
    assert any("from=exact-domain-filtered" in m and "to=default-filtered" in m for m in fallback_records)
    assert any("from=default-filtered" in m and "to=default-unfiltered" in m for m in fallback_records)
    assert any("from=default-unfiltered" in m and "to=www-unfiltered" in m for m in fallback_records)
    httpx_fallback_records = [m for m in fallback_records if "transport_mode=urllib" not in m]
    urllib_fallback_records = [m for m in fallback_records if "transport_mode=urllib" in m]
    assert all("reason=RemoteProtocolError" in m for m in httpx_fallback_records)
    assert all("reason=URLError" in m for m in urllib_fallback_records)

    final_records = [m for m in messages if "all query variants failed" in m]
    assert len(final_records) == 3
    assert all("variants=5" in m for m in final_records)

    transport_fallback_records = [m for m in messages if "transport fallback" in m]
    assert len(transport_fallback_records) == 2
    assert "from=default" in transport_fallback_records[0]
    assert "to=no-env" in transport_fallback_records[0]
    assert "from=no-env" in transport_fallback_records[1]
    assert "to=urllib" in transport_fallback_records[1]

    all_transports_records = [m for m in messages if "all transports failed" in m]
    assert len(all_transports_records) == 1
    assert "transports=3" in all_transports_records[0]
    assert "last_error_type=URLError" in all_transports_records[0]


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
    # The two "exact" (wildcard-free) variants have allow_empty_fallback
    # so a 0-candidate result there falls through, but default-filtered
    # (the first *wildcard* variant) still terminates on a 0-candidate
    # result without falling back further, same as before the exact
    # variants were added.
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason
    # exact-domain-unfiltered and exact-domain-filtered each fall through
    # on their own empty result (1 call each), then default-filtered
    # terminates on its own empty result (1 call) — 3 calls total, never
    # reaching default-unfiltered/www-unfiltered.
    assert calls["count"] == 3


def test_search_logs_query_variant_in_request_start(monkeypatch, caplog):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    # exact-domain-unfiltered (the first variant tried) succeeds
    # immediately.
    assert len(start_records) == 1
    assert "query_variant=exact-domain-unfiltered" in start_records[0]


def test_search_logs_query_variant_in_success_message_after_fallback(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        # Every variant fails except default-unfiltered (url=domain/*,
        # no filters) — forces a fallback across exact-domain-unfiltered,
        # exact-domain-filtered, and default-filtered before succeeding.
        if url_param == "cybozu.co.jp/*" and not has_filter:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

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
    _patch_urllib_persistent_failure(monkeypatch)

    search_common_crawl_domain("www.cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # 4 variants (exact-domain-unfiltered, exact-domain-filtered,
    # default-filtered, default-unfiltered) for a domain that already
    # starts with "www." — no doubled-up "www.www." variant appended.
    # 4 variants x 3 attempts x 2 httpx transport modes (default, no-env)
    # — the urllib transport mode's calls go through the separate
    # _patch_urllib_persistent_failure fake, not this httpx one.
    assert calls["count"] == 24
    assert all(u in ("www.cybozu.co.jp", "www.cybozu.co.jp/*") for u in seen_urls)
    assert not any(u.startswith("www.www.") for u in seen_urls)


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
    # A persistent failure exhausts all 3 transport modes
    # (fix/common-crawl-index-trust-env-fallback,
    # fix/common-crawl-index-urllib-fallback): 3 attempts x 3 modes.
    sleep_calls = _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    assert "network or timeout" in resolution.reason
    # 2 httpx transport modes (default, no-env) x 3 attempts.
    assert calls["count"] == 6
    assert sleep_calls == [0.5, 1.0, 0.5, 1.0, 0.5, 1.0]


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
    _patch_urllib_persistent_failure(monkeypatch)
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
    # exact-domain-unfiltered/exact-domain-filtered fall through on their
    # own empty result; default-filtered (the first wildcard variant)
    # then terminates on its own empty result — 3 start records total,
    # each with the same headers.
    assert len(start_records) == 3
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
    _patch_urllib_persistent_failure(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert result.reason == "Common Crawl Index API request failed due to a network or timeout error."


# --- transport-mode (trust_env=False) fallback ----------------------------------
# Added 2026-07-29 (fix/common-crawl-index-trust-env-fallback) — Render logs
# showed *every* query variant failing with httpx.RemoteProtocolError even with
# explicit headers in place, so query shape and headers alone don't explain it.
# These tests lock in that a persistent transport-layer failure under the
# default transport falls back to a `trust_env=False` ("no-env") retry of the
# same query variants before finally giving up.


def test_search_falls_back_to_no_env_transport_after_default_exhausts_on_remote_protocol_error(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_trust_env = []

    def fake_get(url, **kwargs):
        seen_trust_env.append(kwargs.get("trust_env", "NOT_SET"))
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # Default transport exhausted all 5 variants (3 attempts each = 15
    # calls) before the no-env transport succeeded on its first variant.
    assert seen_trust_env.count("NOT_SET") == 15
    assert seen_trust_env.count(False) == 1


def test_search_falls_back_to_no_env_transport_after_default_exhausts_on_read_timeout(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.ReadTimeout("The read operation timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_falls_back_to_no_env_transport_after_default_exhausts_on_503(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        return httpx.Response(503, text="Service Unavailable", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_all_transports_fail_returns_unavailable_with_unchanged_reason(monkeypatch):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert result.reason == "Common Crawl Index API request failed due to a network or timeout error."


def test_search_does_not_fall_back_to_no_env_on_http_400(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(400, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "400" in result.reason
    # Only the first query variant's first attempt under the default
    # transport — no retry, no query fallback, no transport fallback.
    assert calls["count"] == 1


def test_search_does_not_fall_back_to_no_env_on_http_404(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert calls["count"] == 1


def test_search_does_not_fall_back_to_no_env_on_zero_candidates(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason
    # exact-domain-unfiltered and exact-domain-filtered fall through on
    # their own empty result (query-variant fallback, not transport
    # fallback), then default-filtered terminates on its own empty
    # result — 3 calls total, all still under the default transport (no
    # no-env fallback is triggered by an empty result).
    assert calls["count"] == 3


def test_search_logs_transport_mode_default_in_request_start(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    # exact-domain-unfiltered/exact-domain-filtered fall through on their
    # own empty result; default-filtered (the first wildcard variant)
    # then terminates on its own empty result — 3 start records total,
    # all still under the default transport.
    assert len(start_records) == 3
    assert all("transport_mode=default" in m for m in start_records)


def test_search_logs_transport_mode_no_env_after_fallback(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    no_env_start_records = [
        r.message for r in caplog.records if "request start" in r.message and "transport_mode=no-env" in r.message
    ]
    assert len(no_env_start_records) == 1


def test_search_logs_transport_fallback_message(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    fallback_records = [r.message for r in caplog.records if "transport fallback" in r.message]
    assert len(fallback_records) == 1
    assert "from=default" in fallback_records[0]
    assert "to=no-env" in fallback_records[0]
    assert "reason=RemoteProtocolError" in fallback_records[0]


def test_search_logs_success_with_transport_mode_no_env(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    success_records = [r.message for r in caplog.records if "request succeeded" in r.message]
    assert len(success_records) == 1
    assert "transport_mode=no-env" in success_records[0]
    assert "query_variant=exact-domain-unfiltered" in success_records[0]
    assert "attempt=1/3" in success_records[0]
    assert "candidates=1" in success_records[0]


def test_search_logs_all_transports_failed_message(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    final_records = [r.message for r in caplog.records if "all transports failed" in r.message]
    assert len(final_records) == 1
    assert "transports=3" in final_records[0]
    # The urllib transport mode (tried last) fails with URLError.
    assert "last_error_type=URLError" in final_records[0]


def test_search_no_env_transport_passes_trust_env_false(monkeypatch):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)
    seen_trust_env = []

    def fake_get(url, **kwargs):
        seen_trust_env.append(kwargs.get("trust_env", "NOT_SET"))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # First 15 calls (default transport, 5 variants x 3 attempts) never
    # set trust_env; next 15 calls (no-env transport) always pass
    # trust_env=False. The urllib transport mode (tried last) never
    # calls httpx.get at all.
    assert seen_trust_env[:15] == ["NOT_SET"] * 15
    assert seen_trust_env[15:30] == [False] * 15
    assert len(seen_trust_env) == 30


def test_search_headers_are_maintained_across_transport_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    expected_headers = {
        "User-Agent": "AI-Visibility-Platform-MVP",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }
    assert all(h == expected_headers for h in seen_headers)


def test_search_query_variant_fallback_still_works_within_a_transport_mode(monkeypatch):
    # Regression guard: query-variant fallback (within the default
    # transport) must still work exactly as before transport-mode
    # fallback was added.
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        has_filter = any(k == "filter" for k, _ in kwargs.get("params", []))
        if has_filter:
            raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_retry_still_works_within_a_transport_mode_and_query_variant(monkeypatch):
    # Regression guard: retry within a single (transport_mode,
    # query_variant) pair must still work exactly as before.
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


def test_search_transport_fallback_does_not_affect_candidate_parsing(monkeypatch):
    # Regression guard: candidate parsing behaves identically regardless
    # of which transport mode produced the 200 response.
    _patch_sleep(monkeypatch)
    body = _cdxj_line(
        url="https://cybozu.co.jp/",
        timestamp="20260115000000",
        status="200",
        mime="text/html",
        digest="ABC123",
    )

    def fake_get(url, **kwargs):
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate = result.candidates[0]
    assert candidate.url == "https://cybozu.co.jp/"
    assert candidate.timestamp == "20260115000000"
    assert candidate.status == 200
    assert candidate.mime == "text/html"
    assert candidate.digest == "ABC123"
    assert candidate.source == "common_crawl"


# --- transport-mode fallback (collinfo.json / _fetch_latest_index) -------------


def test_fetch_latest_index_falls_back_to_no_env_transport_after_default_exhausts(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-08"
    # 3 attempts under default transport, then 1 successful attempt
    # under no-env.
    assert calls["count"] == 4


def test_fetch_latest_index_headers_are_maintained_across_transport_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_headers = []

    def fake_get(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        if kwargs.get("trust_env") is False:
            return httpx.Response(200, json=_collinfo_payload("CC-MAIN-2026-08"), request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolve_common_crawl_index(_LATEST_SETTINGS)

    expected_headers = {
        "User-Agent": "AI-Visibility-Platform-MVP",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Connection": "close",
    }
    assert all(h == expected_headers for h in seen_headers)


def test_fetch_latest_index_logs_all_transports_failed(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

    def fake_get(url, **kwargs):
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    final_records = [r.message for r in caplog.records if "all transports failed" in r.message]
    assert len(final_records) == 1
    assert "transports=3" in final_records[0]


def test_fetch_latest_index_does_not_fall_back_to_no_env_on_invalid_json(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="not json", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    # A 200-but-invalid-JSON response is terminal — never retried, never
    # transport-fallback-eligible.
    assert calls["count"] == 1


# --- urllib transport-mode fallback ----------------------------------------------
# Added 2026-07-29 (fix/common-crawl-index-urllib-fallback) — Render logs showed
# *both* httpx transport modes (default and no-env/trust_env=False) still
# exhausting every query variant with httpx.RemoteProtocolError, pointing at an
# httpx-specific transport/Render incompatibility rather than anything
# query-shape/header/proxy-related. These tests lock in that a persistent
# failure across both httpx transports falls back to a third "urllib" mode
# that bypasses httpx entirely via Python's standard library urllib.request.


def _always_raise_remote_protocol_error(url, **kwargs):
    raise httpx.RemoteProtocolError(
        "Server disconnected without sending a response.", request=httpx.Request("GET", url)
    )


def test_search_falls_back_to_urllib_after_both_httpx_transports_exhaust(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_urlopen(request, timeout=None):
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://cybozu.co.jp/"


def test_search_urllib_retry_succeeds_on_second_attempt(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("disconnected")
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    assert calls["count"] == 2


def test_search_urllib_candidate_parsing_is_unchanged(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(
        url="https://cybozu.co.jp/",
        timestamp="20260115000000",
        status="200",
        mime="text/html",
        digest="ABC123",
    )

    def fake_urlopen(request, timeout=None):
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    candidate = result.candidates[0]
    assert candidate.url == "https://cybozu.co.jp/"
    assert candidate.timestamp == "20260115000000"
    assert candidate.status == 200
    assert candidate.mime == "text/html"
    assert candidate.digest == "ABC123"
    assert candidate.source == "common_crawl"


def test_search_urllib_retries_on_503(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _fake_http_error(request.full_url, 503, "Service Unavailable")
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert calls["count"] == 2


def test_search_urllib_does_not_retry_on_400(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        raise _fake_http_error(request.full_url, 400, "")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "400" in result.reason
    # Only the urllib transport's first query variant's first attempt —
    # no retry, no query fallback.
    assert calls["count"] == 1


def test_search_urllib_does_not_retry_on_404(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        raise _fake_http_error(request.full_url, 404, "")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert calls["count"] == 1


def test_search_urllib_body_preview_is_truncated_to_200_chars(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    huge_body = "x" * 5000

    def fake_urlopen(request, timeout=None):
        raise _fake_http_error(request.full_url, 503, huge_body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    urllib_non_200_records = [
        r.message for r in caplog.records if "non-200" in r.message and "transport_mode=urllib" in r.message
    ]
    assert len(urllib_non_200_records) >= 1
    assert len(urllib_non_200_records[0]) < 400
    assert huge_body not in urllib_non_200_records[0]


def test_search_urllib_sends_expected_headers(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert len(seen_requests) > 0
    request = seen_requests[0]
    assert request.get_header("User-agent") == "AI-Visibility-Platform-MVP"
    assert request.get_header("Accept") == "application/json, text/plain;q=0.9, */*;q=0.8"
    assert request.get_header("Connection") == "close"


def test_search_urllib_uses_common_crawl_user_agent_setting(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    settings = CommonCrawlSettings(
        enabled=True,
        index="CC-MAIN-2026-08",
        max_results=5,
        timeout_seconds=10.0,
        user_agent="My-Custom-Agent/2.0",
    )
    search_common_crawl_domain("cybozu.co.jp", settings)

    assert seen_requests[0].get_header("User-agent") == "My-Custom-Agent/2.0"


def test_search_urllib_request_url_matches_logged_request_url(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    urllib_start_records = [
        r.message for r in caplog.records if "request start" in r.message and "transport_mode=urllib" in r.message
    ]
    assert len(urllib_start_records) >= 1
    logged_request_url = urllib_start_records[0].split("request_url=", 1)[1]
    assert seen_requests[0].full_url == logged_request_url


def test_search_urllib_encodes_multiple_filter_params(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    # Calls 0-2 are exact-domain-unfiltered's 3 attempts (no "filter"
    # param at all); call 3 is exact-domain-filtered's 1st attempt — it
    # has 2 "filter" params, both of which must survive
    # urlencode(..., doseq=True).
    exact_filtered_url = seen_requests[3].full_url
    assert "filter=status%3A200" in exact_filtered_url
    assert "filter=mime%3Atext%2Fhtml" in exact_filtered_url


def test_search_urllib_builds_correct_urls_for_each_query_variant(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    urls = [request.full_url for request in seen_requests]
    assert any("url=cybozu.co.jp%2F%2A" in u and "filter=status%3A200" in u for u in urls)
    assert any("url=cybozu.co.jp%2F%2A" in u and "filter" not in u for u in urls)
    assert any("url=www.cybozu.co.jp%2F%2A" in u for u in urls)


def test_search_logs_transport_mode_urllib_in_request_start(monkeypatch, caplog):
    _patch_sleep(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    urllib_start_records = [m for m in start_records if "transport_mode=urllib" in m]
    assert len(urllib_start_records) >= 1


def test_search_logs_success_with_transport_mode_urllib(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_urlopen(request, timeout=None):
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    success_records = [r.message for r in caplog.records if "request succeeded" in r.message]
    assert len(success_records) == 1
    assert "transport_mode=urllib" in success_records[0]
    assert "query_variant=exact-domain-unfiltered" in success_records[0]
    assert "candidates=1" in success_records[0]


def test_search_logs_urllib_failure_error_type(monkeypatch, caplog):
    _patch_sleep(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    urllib_failure_records = [
        r.message for r in caplog.records if "request failed" in r.message and "transport_mode=urllib" in r.message
    ]
    assert len(urllib_failure_records) >= 1
    assert "error_type=URLError" in urllib_failure_records[0]


def test_search_all_transports_failed_log_has_transports_equal_3(monkeypatch, caplog):
    _patch_sleep(monkeypatch)
    _patch_urllib_persistent_failure(monkeypatch)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)

    with caplog.at_level(logging.WARNING, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    final_records = [r.message for r in caplog.records if "all transports failed" in r.message]
    assert len(final_records) == 1
    assert "transports=3" in final_records[0]


def test_search_urllib_headers_are_maintained_across_query_variant_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        has_filter = "filter=" in request.full_url
        if has_filter:
            raise urllib.error.URLError("still failing")
        return _FakeUrllibResponse(200, body)

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    for request in seen_requests:
        assert request.get_header("User-agent") == "AI-Visibility-Platform-MVP"
        assert request.get_header("Accept") == "application/json, text/plain;q=0.9, */*;q=0.8"
        assert request.get_header("Connection") == "close"


def test_search_does_not_fall_back_to_urllib_on_http_400(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(400, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "400" in result.reason
    # Only the first query variant's first attempt under the default
    # transport — no retry, no query fallback, no transport fallback.
    assert calls["count"] == 1


def test_search_does_not_fall_back_to_urllib_on_zero_candidates(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason
    # exact-domain-unfiltered and exact-domain-filtered fall through on
    # their own empty result (query-variant fallback), then
    # default-filtered terminates on its own empty result — 3 calls
    # total, all under the default transport (no urllib fallback).
    assert calls["count"] == 3


# --- urllib transport-mode fallback (collinfo.json / _fetch_latest_index) -----


def test_fetch_latest_index_falls_back_to_urllib_after_both_httpx_transports_exhaust(monkeypatch):
    _patch_sleep(monkeypatch)

    def fake_urlopen(request, timeout=None):
        return _FakeUrllibResponse(200, json.dumps(_collinfo_payload("CC-MAIN-2026-08")))

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is True
    assert resolution.crawl_index == "CC-MAIN-2026-08"


def test_fetch_latest_index_urllib_sends_expected_headers(monkeypatch):
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        return _FakeUrllibResponse(200, json.dumps(_collinfo_payload("CC-MAIN-2026-08")))

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    resolve_common_crawl_index(_LATEST_SETTINGS)

    assert len(seen_requests) == 1
    assert seen_requests[0].get_header("User-agent") == "AI-Visibility-Platform-MVP"
    assert seen_requests[0].get_header("Accept") == "application/json, text/plain;q=0.9, */*;q=0.8"
    assert seen_requests[0].get_header("Connection") == "close"


def test_fetch_latest_index_urllib_url_has_no_query_string(monkeypatch):
    # collinfo.json is fetched with no query params at all.
    _patch_sleep(monkeypatch)
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        return _FakeUrllibResponse(200, json.dumps(_collinfo_payload("CC-MAIN-2026-08")))

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    resolve_common_crawl_index(_LATEST_SETTINGS)

    assert seen_requests[0].full_url == COLLINFO_URL


def test_fetch_latest_index_urllib_does_not_retry_on_non_retryable_non_200(monkeypatch):
    _patch_sleep(monkeypatch)
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        raise _fake_http_error(request.full_url, 404, "")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)

    resolution = resolve_common_crawl_index(_LATEST_SETTINGS)

    assert resolution.success is False
    assert calls["count"] == 1


# --- exact-domain (wildcard-free) query variant ---------------------------------
# Added 2026-07-29 (fix/common-crawl-index-exact-domain-query) — manual
# verification against the real Index API found that `url={domain}` (no "/*"
# wildcard) reliably returns JSON, while `url={domain}/*` (with the wildcard,
# plus filters) intermittently returned 503 or triggered the RemoteProtocolError
# Render kept hitting across every transport mode. These tests lock in that the
# wildcard-free "exact" variants are tried first, that they use `url=domain`
# (never `url=domain/*`), and that a 0-candidate result there falls through to
# the next variant (unlike the wildcard variants).


def test_build_query_variants_includes_exact_domain_unfiltered_first(monkeypatch):
    variants = common_crawl_index._build_query_variants("cybozu.co.jp", 5)

    assert len(variants) == 5
    first_name, first_url_pattern, first_params, first_allow_empty_fallback = variants[0]
    assert first_name == "exact-domain-unfiltered"
    assert first_url_pattern == "cybozu.co.jp"
    assert ("url", "cybozu.co.jp") in first_params
    assert ("output", "json") in first_params
    assert ("limit", "5") in first_params
    assert not any(k == "filter" for k, _ in first_params)
    assert first_allow_empty_fallback is True


def test_build_query_variants_includes_exact_domain_filtered_second(monkeypatch):
    variants = common_crawl_index._build_query_variants("cybozu.co.jp", 5)

    second_name, second_url_pattern, second_params, second_allow_empty_fallback = variants[1]
    assert second_name == "exact-domain-filtered"
    assert second_url_pattern == "cybozu.co.jp"
    assert ("url", "cybozu.co.jp") in second_params
    assert ("filter", "status:200") in second_params
    assert ("filter", "mime:text/html") in second_params
    assert ("limit", "5") in second_params
    assert second_allow_empty_fallback is True


def test_build_query_variants_wildcard_variants_still_present_and_ordered_last(monkeypatch):
    variants = common_crawl_index._build_query_variants("cybozu.co.jp", 5)

    names = [name for name, _, _, _ in variants]
    assert names == [
        "exact-domain-unfiltered",
        "exact-domain-filtered",
        "default-filtered",
        "default-unfiltered",
        "www-unfiltered",
    ]
    # Wildcard variants keep allow_empty_fallback=False, unchanged.
    for name, _, _, allow_empty_fallback in variants[2:]:
        assert allow_empty_fallback is False


def test_search_first_request_url_has_no_wildcard(monkeypatch, caplog):
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    assert len(start_records) >= 1
    first_message = start_records[0]
    assert (
        "request_url=https://index.commoncrawl.org/CC-MAIN-2026-08-index?url=cybozu.co.jp&output=json&limit=5"
        in first_message
    )
    assert "cybozu.co.jp%2F%2A" not in first_message


def test_search_exact_domain_unfiltered_succeeds_without_calling_wildcard_query(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # Only exact-domain-unfiltered was called — no wildcard query variant
    # was ever reached.
    assert calls["count"] == 1


def test_search_exact_domain_unfiltered_falls_back_after_remote_protocol_error(monkeypatch):
    _patch_sleep(monkeypatch)
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_params = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        seen_params.append(params)
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        is_exact_domain_unfiltered = url_param == "cybozu.co.jp" and not has_filter
        if is_exact_domain_unfiltered:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=httpx.Request("GET", url)
            )
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # exact-domain-unfiltered exhausted its 3 attempts, then
    # exact-domain-filtered succeeded on its first attempt.
    assert len(seen_params) == 4


def test_search_exact_domain_unfiltered_zero_candidates_falls_through_to_next_variant(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_urls = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        seen_urls.append((url_param, has_filter))
        if url_param == "cybozu.co.jp" and not has_filter:
            # exact-domain-unfiltered: succeeds but returns 0 candidates.
            return httpx.Response(200, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # exact-domain-unfiltered (0 candidates) then exact-domain-filtered
    # (succeeds) — 2 calls total, falling through rather than
    # terminating on the empty result.
    assert seen_urls == [("cybozu.co.jp", False), ("cybozu.co.jp", True)]


def test_search_exact_domain_filtered_zero_candidates_falls_through_to_default_filtered(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")
    seen_urls = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        seen_urls.append((url_param, has_filter))
        if url_param == "cybozu.co.jp":
            # Both exact variants succeed but return 0 candidates.
            return httpx.Response(200, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1
    # exact-domain-unfiltered (0) -> exact-domain-filtered (0) ->
    # default-filtered (succeeds).
    assert seen_urls == [
        ("cybozu.co.jp", False),
        ("cybozu.co.jp", True),
        ("cybozu.co.jp/*", True),
    ]


def test_search_wildcard_variant_zero_candidates_still_terminates(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason
    # exact-domain-unfiltered (0) -> exact-domain-filtered (0) ->
    # default-filtered (0, terminal — wildcard variants don't fall
    # through on an empty result).
    assert calls["count"] == 3


def test_search_logs_no_candidates_trying_next_variant_message(monkeypatch, caplog):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        url_param = next((v for k, v in params if k == "url"), None)
        if url_param == "cybozu.co.jp":
            return httpx.Response(200, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    no_candidates_records = [
        r.message for r in caplog.records if "returned no candidates; trying next variant" in r.message
    ]
    assert len(no_candidates_records) == 2
    assert "from=exact-domain-unfiltered" in no_candidates_records[0]
    assert "to=exact-domain-filtered" in no_candidates_records[0]
    assert "from=exact-domain-filtered" in no_candidates_records[1]
    assert "to=default-filtered" in no_candidates_records[1]


def test_search_logs_query_variant_exact_domain_unfiltered_on_success(monkeypatch, caplog):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    with caplog.at_level(logging.INFO, logger="services.common_crawl_index"):
        search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    start_records = [r.message for r in caplog.records if "request start" in r.message]
    assert len(start_records) == 1
    assert "query_variant=exact-domain-unfiltered" in start_records[0]


def test_search_exact_domain_candidate_parsing_is_unchanged(monkeypatch):
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


def test_search_exact_domain_variant_used_under_no_env_transport(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_get(url, **kwargs):
        params = kwargs.get("params", [])
        url_param = next((v for k, v in params if k == "url"), None)
        has_filter = any(k == "filter" for k, _ in params)
        if kwargs.get("trust_env") is False and url_param == "cybozu.co.jp" and not has_filter:
            return httpx.Response(200, text=body, request=httpx.Request("GET", url))
        raise httpx.RemoteProtocolError("disconnected", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)
    _patch_sleep(monkeypatch)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_exact_domain_variant_used_under_urllib_transport(monkeypatch):
    body = _cdxj_line(url="https://cybozu.co.jp/")

    def fake_urlopen(request, timeout=None):
        if request.full_url == f"{common_crawl_index.COMMON_CRAWL_HOST}/CC-MAIN-2026-08-index?url=cybozu.co.jp&output=json&limit=5":
            return _FakeUrllibResponse(200, body)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)
    _patch_sleep(monkeypatch)

    result = search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    assert result.status == "real"
    assert len(result.candidates) == 1


def test_search_urllib_exact_domain_url_has_no_wildcard_encoding(monkeypatch):
    seen_requests = []

    def fake_urlopen(request, timeout=None):
        seen_requests.append(request)
        raise urllib.error.URLError("still failing")

    monkeypatch.setattr(common_crawl_index.httpx, "get", _always_raise_remote_protocol_error)
    monkeypatch.setattr(common_crawl_index.urllib.request, "urlopen", fake_urlopen)
    _patch_sleep(monkeypatch)

    search_common_crawl_domain("cybozu.co.jp", _FIXED_INDEX_SETTINGS)

    first_url = seen_requests[0].full_url
    assert first_url == "https://index.commoncrawl.org/CC-MAIN-2026-08-index?url=cybozu.co.jp&output=json&limit=5"
    assert "%2F%2A" not in first_url


def test_search_retry_and_query_fallback_still_work_with_exact_domain_variants(monkeypatch):
    # Regression guard: retry within a variant, and fallback across
    # variants, both still work exactly as before the exact-domain
    # variants were added — this exercises retry (1st attempt fails),
    # then success on the 2nd attempt of the very first variant tried.
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
