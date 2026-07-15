import pytest

from services.document_cleaner import MAX_BODY_TEXT_LENGTH, clean_html_to_text, extract_title


def test_clean_html_to_text_keeps_visible_body_content():
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
    text = clean_html_to_text(html)

    assert "料金プラン" in text
    assert "評判" in text


@pytest.mark.parametrize(
    "tag",
    ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg"],
)
def test_clean_html_to_text_excludes_noise_tags(tag):
    html = f"""
    <html>
      <body>
        <{tag}>この文字列はノイズです</{tag}>
        <main><p>本文はこちらです。</p></main>
      </body>
    </html>
    """
    text = clean_html_to_text(html)

    assert "ノイズ" not in text
    assert "本文" in text


def test_clean_html_to_text_removes_cookie_banner_like_elements():
    html = (
        '<html><body><div class="cookie-consent-banner">'
        "Cookieの利用に同意してください</div>"
        "<main><p>本文はこちらです。</p></main></body></html>"
    )
    text = clean_html_to_text(html)

    assert "同意してください" not in text
    assert "本文" in text


def test_clean_html_to_text_removes_ad_like_elements():
    html = (
        '<html><body><div class="advertisement-banner">広告コンテンツです</div>'
        "<main><p>本文はこちらです。</p></main></body></html>"
    )
    text = clean_html_to_text(html)

    assert "広告コンテンツ" not in text
    assert "本文" in text


def test_clean_html_to_text_does_not_over_remove_legitimate_content():
    # "notice"/"ad" as bare substrings must not accidentally strip real
    # content — e.g. a genuine "お知らせ" (notices) section or a word
    # containing "ad" like "advice".
    html = (
        '<html><body><section id="oshirase"><p>大切なお知らせがあります。</p></section>'
        "<main><p>advice記事の本文です。</p></main></body></html>"
    )
    text = clean_html_to_text(html)

    assert "お知らせ" in text
    assert "advice記事" in text


def test_clean_html_to_text_handles_empty_html_without_raising():
    assert clean_html_to_text("") == ""


def test_clean_html_to_text_handles_html_with_no_body_text_without_raising():
    assert clean_html_to_text("<html><head></head><body></body></html>") == ""


def test_clean_html_to_text_truncates_to_max_length():
    html = f"<html><body><p>{'あ' * (MAX_BODY_TEXT_LENGTH + 1000)}</p></body></html>"

    text = clean_html_to_text(html)

    assert len(text) == MAX_BODY_TEXT_LENGTH


def test_clean_html_to_text_accepts_source_url_without_using_it_yet():
    # source_url is reserved for future domain-specific rules; passing
    # it must not change the result or raise.
    html = "<html><body><p>本文です。</p></body></html>"

    assert clean_html_to_text(html, source_url="https://example.com/a") == clean_html_to_text(html)


def test_extract_title_returns_title_when_present():
    html = "<html><head><title>OpenAIの料金プラン</title></head><body></body></html>"

    assert extract_title(html) == "OpenAIの料金プラン"


def test_extract_title_returns_none_when_missing():
    html = "<html><body><p>本文です。</p></body></html>"

    assert extract_title(html) is None


def test_extract_title_returns_none_for_empty_html():
    assert extract_title("") is None
