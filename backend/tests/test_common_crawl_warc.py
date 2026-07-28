import gzip

import httpx

from services import common_crawl_warc
from services.common_crawl_index import CommonCrawlCandidate
from services.common_crawl_settings import CommonCrawlSettings
from services.common_crawl_warc import (
    MAX_HTML_CHARS,
    MAX_WARC_RANGE_BYTES,
    fetch_common_crawl_warc_record,
)

_SETTINGS = CommonCrawlSettings(
    enabled=True,
    index="CC-MAIN-2026-08",
    max_results=5,
    timeout_seconds=7.5,
    user_agent="Custom-UA/1.0",
)

_FILENAME = "crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz"


def _candidate(**overrides) -> CommonCrawlCandidate:
    fields = {
        "url": "https://cybozu.co.jp/",
        "timestamp": "20260101000000",
        "status": 200,
        "mime": "text/html",
        "digest": "abc123",
        "length": 2000,
        "offset": 1000,
        "filename": _FILENAME,
        "crawl_index": "CC-MAIN-2026-08",
    }
    fields.update(overrides)
    return CommonCrawlCandidate(**fields)


def _warc_record(
    html: bytes,
    content_type: str | None = "text/html; charset=UTF-8",
    http_status: str = "200 OK",
) -> bytes:
    warc_headers = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        b"WARC-Target-URI: https://cybozu.co.jp/\r\n"
    )
    http_headers = f"HTTP/1.1 {http_status}\r\n".encode()
    if content_type is not None:
        http_headers += f"Content-Type: {content_type}\r\n".encode()
    record = warc_headers + b"\r\n" + http_headers + b"\r\n" + html
    return record


def _gzipped_warc_record(**kwargs) -> bytes:
    return gzip.compress(_warc_record(**kwargs))


def _fail_if_called(*args, **kwargs):
    raise AssertionError("httpx.get should not have been called")


# --- validation (no HTTP call) ----------------------------------------------


def test_missing_filename_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(filename=None), _SETTINGS)

    assert result.status == "unavailable"
    assert "filename" in result.reason


def test_empty_filename_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(filename="   "), _SETTINGS)

    assert result.status == "unavailable"
    assert "filename" in result.reason


def test_missing_offset_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(offset=None), _SETTINGS)

    assert result.status == "unavailable"
    assert "offset or length" in result.reason


def test_missing_length_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(length=None), _SETTINGS)

    assert result.status == "unavailable"
    assert "offset or length" in result.reason


def test_zero_length_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(length=0), _SETTINGS)

    assert result.status == "unavailable"
    assert "offset or length" in result.reason


def test_negative_offset_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(_candidate(offset=-1), _SETTINGS)

    assert result.status == "unavailable"
    assert "offset or length" in result.reason


def test_length_too_large_returns_unavailable_without_http(monkeypatch):
    monkeypatch.setattr(common_crawl_warc.httpx, "get", _fail_if_called)

    result = fetch_common_crawl_warc_record(
        _candidate(length=MAX_WARC_RANGE_BYTES + 1), _SETTINGS
    )

    assert result.status == "unavailable"
    assert "too large" in result.reason


# --- HTTP request shape ------------------------------------------------------


def test_range_header_and_url_are_correct(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")
        return httpx.Response(
            200, content=_gzipped_warc_record(html=b"<html>ok</html>"), request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(offset=1000, length=2000), _SETTINGS)

    assert result.status == "real"
    assert captured["url"] == f"https://data.commoncrawl.org/{_FILENAME}"
    assert captured["headers"]["Range"] == "bytes=1000-2999"
    assert captured["headers"]["User-Agent"] == "Custom-UA/1.0"
    assert captured["timeout"] == 7.5


def test_accepts_status_200(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200, content=_gzipped_warc_record(html=b"<html>ok</html>"), request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"


def test_accepts_status_206(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            206, content=_gzipped_warc_record(html=b"<html>ok</html>"), request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"


def test_http_404_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "404" in result.reason


def test_http_500_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "500" in result.reason


def test_network_error_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"


def test_empty_response_body_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, content=b"", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "empty" in result.reason


# --- gzip / HTML extraction ---------------------------------------------------


def test_extracts_html_from_valid_gzip_warc_record(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=b"<html><body>hello</body></html>"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert result.html == "<html><body>hello</body></html>"
    assert result.content_type == "text/html"


def test_allows_application_xhtml_xml_content_type(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(
                html=b"<html>ok</html>", content_type="application/xhtml+xml"
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert result.content_type == "application/xhtml+xml"


def test_rejects_non_html_content_type(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=b"\x89PNG\r\n", content_type="image/png"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "content type" in result.reason
    assert result.html is None


def test_missing_content_type_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=b"<html>ok</html>", content_type=None),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "content type" in result.reason


def test_missing_http_boundary_returns_unavailable(monkeypatch):
    # No blank-line-separated HTTP block at all — just a single WARC-ish blob.
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=gzip.compress(b"not a warc record with no blank line boundary"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "HTTP response body" in result.reason


def test_gzip_decompression_failure_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, content=b"this is not gzip data at all", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "gzip" in result.reason


def test_charset_utf8_is_decoded_correctly(monkeypatch):
    html = "<html>こんにちは</html>".encode("utf-8")

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=html, content_type="text/html; charset=UTF-8"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert result.html == "<html>こんにちは</html>"


def test_charset_shift_jis_is_decoded_correctly(monkeypatch):
    html = "<html>こんにちは</html>".encode("shift_jis")

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=html, content_type="text/html; charset=Shift_JIS"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert result.html == "<html>こんにちは</html>"


def test_unknown_charset_falls_back_to_utf8(monkeypatch):
    html = "<html>hello</html>".encode("utf-8")

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(
                html=html, content_type="text/html; charset=totally-not-a-real-charset"
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert result.html == "<html>hello</html>"


def test_empty_html_body_returns_unavailable(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=b"   "),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert "HTML body was empty" in result.reason


def test_huge_html_is_truncated_not_rejected(monkeypatch):
    huge_html = "<html>" + ("x" * (MAX_HTML_CHARS * 2)) + "</html>"

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=huge_html.encode("utf-8")),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert len(result.html) == MAX_HTML_CHARS


def test_reason_never_contains_a_huge_response_body(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, content=b"not gzip " * 100_000, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "unavailable"
    assert len(result.reason) < 500


def test_reason_never_contains_html_body_on_success(monkeypatch):
    html = b"<html><body>" + b"z" * 5000 + b"</body></html>"

    def fake_get(url, **kwargs):
        return httpx.Response(200, content=_gzipped_warc_record(html=html), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    assert result.status == "real"
    assert len(result.reason) < 200


# --- integration-ish ----------------------------------------------------------


def test_fetch_returns_real_result_with_expected_fields(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            content=_gzipped_warc_record(html=b"<html>hello</html>"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    candidate = _candidate()
    result = fetch_common_crawl_warc_record(candidate, _SETTINGS)

    assert result.status == "real"
    assert result.url == candidate.url
    assert result.crawl_index == candidate.crawl_index
    assert result.content_type == "text/html"
    assert result.html == "<html>hello</html>"
    assert result.fetched_bytes is not None and result.fetched_bytes > 0


def test_result_never_holds_raw_compressed_warc_bytes(monkeypatch):
    raw_gzip = _gzipped_warc_record(html=b"<html>hello</html>")

    def fake_get(url, **kwargs):
        return httpx.Response(200, content=raw_gzip, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_warc.httpx, "get", fake_get)

    result = fetch_common_crawl_warc_record(_candidate(), _SETTINGS)

    for value in vars(result).values():
        if isinstance(value, (bytes, bytearray)):
            raise AssertionError("CommonCrawlFetchResult must not hold raw bytes fields")
    assert raw_gzip not in (result.html or "").encode("utf-8", errors="ignore")


def test_common_crawl_warc_module_is_not_wired_into_main():
    import inspect

    import main

    source = inspect.getsource(main)
    assert "common_crawl_warc" not in source
    assert "fetch_common_crawl_warc_record" not in source
