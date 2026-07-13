import httpx
import pytest

from services import web_fetcher
from services.web_fetcher import _extract_body_text, _is_safe_url, fetch_url_texts


def test_extract_body_text_returns_visible_text():
    html = """
    <html>
      <body>
        <main>
          <h1>OpenAIの料金プランについて</h1>
          <p>OpenAIは料金プランが分かりやすいと評判です。</p>
        </main>
      </body>
    </html>
    """
    text = _extract_body_text(html)

    assert "料金プラン" in text
    assert "評判" in text


@pytest.mark.parametrize("tag", ["script", "style", "nav", "footer"])
def test_extract_body_text_excludes_noise_tags(tag):
    html = f"""
    <html>
      <body>
        <{tag}>この文字列はノイズです</{tag}>
        <main><p>本文はこちらです。</p></main>
      </body>
    </html>
    """
    text = _extract_body_text(html)

    assert "ノイズ" not in text
    assert "本文" in text


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
