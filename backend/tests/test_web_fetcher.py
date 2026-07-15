import threading
import time

import httpx
import pytest

from services import web_fetcher
from services.web_fetcher import UrlFetchResult, _is_safe_url, fetch_url_texts, to_documents

# HTML cleaning/text-extraction itself is tested in test_document_cleaner.py
# now that it lives in services/document_cleaner.py — this file only
# tests that web_fetcher.py correctly delegates to it (see
# test_fetch_url_texts_delegates_cleaning_to_document_cleaner below).


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://[::1]/x",
        "http://192.168.1.10/x",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/x",
    ],
)
def test_is_safe_url_rejects_local_and_private_addresses(url):
    is_safe, reason = _is_safe_url(url)

    assert is_safe is False
    assert reason is not None


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x"])
def test_is_safe_url_rejects_non_http_schemes(url):
    is_safe, reason = _is_safe_url(url)

    assert is_safe is False
    assert reason is not None


def test_is_safe_url_accepts_public_https_url(monkeypatch):
    # Avoid depending on real DNS/network in tests: pretend this
    # hostname resolves to a public IP.
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    is_safe, reason = _is_safe_url("https://example.com/article")

    assert is_safe is True
    assert reason is None


def test_fetch_url_texts_continues_after_one_failure(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    def fake_get(url, **kwargs):
        if "fail" in url:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text="<html><body><p>取得できた本文です。</p></body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web_fetcher.httpx, "get", fake_get)

    results = fetch_url_texts(
        ["https://example.com/ok", "https://example.com/fail"]
    )

    assert results[0].success is True
    assert "本文" in results[0].text
    assert results[1].success is False
    assert results[1].error is not None


def test_fetch_url_texts_rejects_disallowed_url_without_network_call(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.get should not be called for a disallowed URL")

    monkeypatch.setattr(web_fetcher.httpx, "get", fail_if_called)

    results = fetch_url_texts(["http://localhost/x"])

    assert results[0].success is False
    assert "disallowed address" in results[0].error


def test_fetch_url_texts_runs_with_limited_concurrency(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    lock = threading.Lock()
    current = 0
    max_seen = 0

    def fake_get(url, **kwargs):
        nonlocal current, max_seen
        with lock:
            current += 1
            max_seen = max(max_seen, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return httpx.Response(200, text="<p>ok</p>", request=httpx.Request("GET", url))

    monkeypatch.setattr(web_fetcher.httpx, "get", fake_get)

    urls = [f"https://example.com/{i}" for i in range(6)]
    results = fetch_url_texts(urls)

    assert all(r.success for r in results)
    # Actually ran concurrently (not fully sequential)...
    assert max_seen > 1
    # ...but capped at MAX_CONCURRENT_FETCHES, not fully parallel.
    assert max_seen <= web_fetcher.MAX_CONCURRENT_FETCHES


def test_fetch_url_texts_preserves_input_order(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    def fake_get(url, **kwargs):
        # The first URL takes the longest, so if results were ordered
        # by completion time instead of input order, this would catch it.
        if url.endswith("/0"):
            time.sleep(0.1)
        return httpx.Response(
            200, text=f"<p>{url}</p>", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(web_fetcher.httpx, "get", fake_get)

    urls = [f"https://example.com/{i}" for i in range(4)]
    results = fetch_url_texts(urls)

    assert [r.url for r in results] == urls


def test_fetch_url_texts_empty_list_does_not_raise():
    assert fetch_url_texts([]) == []


def test_fetch_url_texts_extracts_title_when_present(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            text="<html><head><title>OpenAIの料金プラン</title></head>"
            "<body><p>本文です。</p></body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web_fetcher.httpx, "get", fake_get)

    results = fetch_url_texts(["https://example.com/article"])

    assert results[0].title == "OpenAIの料金プラン"


def test_fetch_url_texts_title_is_none_when_missing(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(
        web_fetcher.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200, text="<html><body><p>本文です。</p></body></html>", request=httpx.Request("GET", url)
        ),
    )

    results = fetch_url_texts(["https://example.com/article"])

    assert results[0].title is None


def test_to_documents_only_includes_successful_fetches():
    results = [
        UrlFetchResult(
            url="https://example.com/a",
            success=True,
            text="取得できた本文です。",
            title="記事タイトル",
        ),
        UrlFetchResult(url="https://example.com/b", success=False, error="timeout"),
    ]

    documents = to_documents(results)

    assert len(documents) == 1
    document = documents[0]
    assert document.sourceType == "web_fetch"
    assert document.sourceUrl == "https://example.com/a"
    assert document.domain == "example.com"
    assert document.title == "記事タイトル"
    assert document.text == "取得できた本文です。"
    assert document.id  # non-empty, uniquely identifies the Document
    assert document.fetchedAt  # non-empty ISO timestamp


def test_to_documents_returns_empty_list_when_all_fetches_failed():
    results = [
        UrlFetchResult(url="https://example.com/a", success=False, error="boom"),
    ]

    assert to_documents(results) == []


def test_fetch_url_texts_normalizes_cleaned_body_text(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(
        web_fetcher.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200,
            text="<html><body><p>ignored, clean_html_to_text is stubbed below</p></body></html>",
            request=httpx.Request("GET", url),
        ),
    )
    monkeypatch.setattr(
        web_fetcher,
        "clean_html_to_text",
        lambda html, source_url=None: "ＡＩ　Ｖｉｓｉｂｉｌｉｔｙ    Platform",
    )

    results = fetch_url_texts(["https://example.com/article"])

    # web_fetcher ran document_cleaner's output through the Normalizer
    # (normalize_text) rather than storing it as-is.
    assert results[0].text == "AI Visibility Platform"


def test_fetch_url_texts_delegates_cleaning_to_document_cleaner(monkeypatch):
    monkeypatch.setattr(
        web_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(
        web_fetcher.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200,
            text="<html><body><p>本文です。</p></body></html>",
            request=httpx.Request("GET", url),
        ),
    )

    calls = []

    def fake_clean(html, source_url=None):
        calls.append((html, source_url))
        return "クリーニング済みテキスト"

    monkeypatch.setattr(web_fetcher, "clean_html_to_text", fake_clean)

    results = fetch_url_texts(["https://example.com/article"])

    # web_fetcher used document_cleaner's function rather than doing its
    # own HTML parsing, and passed the URL through as source_url.
    assert results[0].text == "クリーニング済みテキスト"
    assert len(calls) == 1
    assert calls[0][1] == "https://example.com/article"
