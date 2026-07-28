from services.common_crawl_document_provider import (
    build_common_crawl_document,
    build_common_crawl_documents,
)
from services.common_crawl_index import CommonCrawlCandidate
from services.common_crawl_warc import CommonCrawlFetchResult

_HTML = (
    "<html><head><title>About Cybozu</title></head>"
    "<body><script>evil()</script>"
    "<p>Cybozu is a company that makes teamwork software.</p>"
    "</body></html>"
)


def _candidate(**overrides) -> CommonCrawlCandidate:
    fields = {
        "url": "https://cybozu.co.jp/about",
        "timestamp": "20260101000000",
        "status": 200,
        "mime": "text/html",
        "digest": "abc123",
        "length": 2000,
        "offset": 1000,
        "filename": "crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz",
        "crawl_index": "CC-MAIN-2026-08",
    }
    fields.update(overrides)
    return CommonCrawlCandidate(**fields)


def _fetch_result(**overrides) -> CommonCrawlFetchResult:
    fields = {
        "status": "real",
        "reason": "Common Crawl WARC record fetched and HTML extracted successfully.",
        "url": "https://cybozu.co.jp/about",
        "crawl_index": "CC-MAIN-2026-08",
        "html": _HTML,
        "content_type": "text/html",
        "fetched_bytes": 4321,
    }
    fields.update(overrides)
    return CommonCrawlFetchResult(**fields)


# --- success -------------------------------------------------------------


def test_build_document_from_real_fetch_result():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    assert result.status == "real"
    assert len(result.documents) == 1


def test_document_source_type_is_common_crawl():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    assert result.documents[0].sourceType == "common_crawl"


def test_document_source_url_is_candidate_url():
    candidate = _candidate(url="https://cybozu.co.jp/about")
    fetch_result = _fetch_result(url="https://cybozu.co.jp/about-mismatched")

    result = build_common_crawl_document(candidate, fetch_result)

    assert result.documents[0].sourceUrl == "https://cybozu.co.jp/about"


def test_metadata_contains_crawl_index():
    result = build_common_crawl_document(_candidate(crawl_index="CC-MAIN-2026-08"), _fetch_result())

    assert result.documents[0].metadata["crawlIndex"] == "CC-MAIN-2026-08"


def test_metadata_contains_warc_filename_offset_length():
    candidate = _candidate(
        filename="crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz",
        offset=1000,
        length=2000,
    )

    result = build_common_crawl_document(candidate, _fetch_result())

    metadata = result.documents[0].metadata
    assert metadata["warcFilename"] == "crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz"
    assert metadata["warcOffset"] == 1000
    assert metadata["warcLength"] == 2000


def test_metadata_contains_fetched_bytes_and_content_type():
    result = build_common_crawl_document(
        _candidate(), _fetch_result(fetched_bytes=9999, content_type="text/html")
    )

    metadata = result.documents[0].metadata
    assert metadata["fetchedBytes"] == 9999
    assert metadata["contentType"] == "text/html"


def test_metadata_contains_remaining_candidate_fields():
    candidate = _candidate(timestamp="20260101000000", mime="text/html", status=200, digest="abc123")

    result = build_common_crawl_document(candidate, _fetch_result())

    metadata = result.documents[0].metadata
    assert metadata["warcTimestamp"] == "20260101000000"
    assert metadata["mime"] == "text/html"
    assert metadata["status"] == 200
    assert metadata["digest"] == "abc123"
    assert metadata["provider"] == "common_crawl"


def test_html_body_becomes_cleaned_text():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    text = result.documents[0].text
    assert "Cybozu is a company that makes teamwork software." in text


def test_html_tags_do_not_remain_in_cleaned_text():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    text = result.documents[0].text
    assert "<" not in text
    assert "script" not in text
    assert "evil()" not in text


# --- failure ---------------------------------------------------------------


def test_non_real_fetch_result_is_unavailable():
    result = build_common_crawl_document(_candidate(), _fetch_result(status="unavailable", html=None))

    assert result.status == "unavailable"
    assert result.documents == ()


def test_missing_html_is_unavailable():
    result = build_common_crawl_document(_candidate(), _fetch_result(html=None))

    assert result.status == "unavailable"
    assert "HTML" in result.reason


def test_empty_html_is_unavailable():
    result = build_common_crawl_document(_candidate(), _fetch_result(html="   "))

    assert result.status == "unavailable"


def test_cleaned_text_empty_after_cleaner_is_unavailable():
    html_with_only_excluded_content = "<html><body><script>evil()</script>   </body></html>"

    result = build_common_crawl_document(_candidate(), _fetch_result(html=html_with_only_excluded_content))

    assert result.status == "unavailable"
    assert "cleaned text" in result.reason.lower()


# --- safety ------------------------------------------------------------------


def test_reason_never_contains_html_or_warc_body_on_failure():
    huge_html = "<html><body>" + ("z" * 100_000) + "</body></html>"

    result = build_common_crawl_document(_candidate(), _fetch_result(html=None))

    assert result.status == "unavailable"
    assert len(result.reason) < 200
    assert huge_html not in result.reason


def test_reason_never_contains_html_body_on_success():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    assert len(result.reason) < 200
    assert "Cybozu" not in result.reason


def test_no_raw_bytes_fields_anywhere_in_document():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    document = result.documents[0]
    for value in [document.text, document.title, document.sourceUrl, document.domain]:
        assert not isinstance(value, (bytes, bytearray))
    for value in document.metadata.values():
        assert not isinstance(value, (bytes, bytearray))


def test_no_secret_like_fields_in_metadata():
    result = build_common_crawl_document(_candidate(), _fetch_result())

    metadata = result.documents[0].metadata
    for forbidden in ("login", "password", "api_key", "apiKey", "secret", "token"):
        assert forbidden not in metadata


# --- list wrapper --------------------------------------------------------


def test_build_documents_all_succeed():
    pairs = [
        (_candidate(url="https://cybozu.co.jp/a"), _fetch_result(url="https://cybozu.co.jp/a")),
        (_candidate(url="https://cybozu.co.jp/b"), _fetch_result(url="https://cybozu.co.jp/b")),
    ]

    result = build_common_crawl_documents(pairs)

    assert result.status == "real"
    assert len(result.documents) == 2


def test_build_documents_mixed_success_and_failure():
    pairs = [
        (_candidate(url="https://cybozu.co.jp/a"), _fetch_result(url="https://cybozu.co.jp/a")),
        (_candidate(url="https://cybozu.co.jp/b"), _fetch_result(status="unavailable", html=None)),
    ]

    result = build_common_crawl_documents(pairs)

    assert result.status == "real"
    assert len(result.documents) == 1
    assert result.documents[0].sourceUrl == "https://cybozu.co.jp/a"


def test_build_documents_all_fail_is_unavailable():
    pairs = [
        (_candidate(), _fetch_result(status="unavailable", html=None)),
    ]

    result = build_common_crawl_documents(pairs)

    assert result.status == "unavailable"
    assert result.documents == ()


def test_build_documents_empty_input_is_unavailable():
    result = build_common_crawl_documents([])

    assert result.status == "unavailable"


# --- regression: existing document providers still work ----------------------


def test_existing_sample_documents_provider_still_works():
    from services.sample_documents import build_sample_documents_as_documents

    documents = build_sample_documents_as_documents("TestBrand")

    assert len(documents) > 0
    assert all(document.sourceType == "development_sample" for document in documents)


def test_existing_web_fetcher_to_documents_still_works():
    from services.web_fetcher import UrlFetchResult, to_documents

    fetch_results = [
        UrlFetchResult(url="https://example.com/", success=True, text="hello", title="Example")
    ]

    documents = to_documents(fetch_results)

    assert len(documents) == 1
    assert documents[0].sourceType == "web_fetch"
