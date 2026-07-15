"""HTML → analyzable plain text, decoupled from *how* the HTML was
obtained (URL fetch today; in principle Common Crawl WARC records
tomorrow — see docs/11_architecture_v1.md "4. Document Pipeline").

This is the Pipeline's "Cleaner" stage: strip elements that are never
part of the text we want to analyze (scripts, nav, cookie banners,
ad slots, ...) and produce a plain-text string. It does not decide
*what* to fetch (that's web_fetcher.py's Provider role) and it does
not do the fuller text normalization (full-width/half-width, etc.) —
that is a future Normalizer stage, deliberately out of scope here.
Only minimal whitespace collapsing is done.
"""

from bs4 import BeautifulSoup
from bs4.element import Tag

MAX_BODY_TEXT_LENGTH = 5000

# Elements that are never part of the "body text" we want to analyze.
EXCLUDED_TAGS = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "template",
    "form",
    "iframe",
    "svg",
]

# Cookie-consent banners and ad slots aren't identifiable by tag name,
# so they're matched by common class/id naming conventions instead.
# Deliberately narrow, hyphenated/compound substrings (not bare words
# like "ad" or "notice") to avoid decomposing legitimate body content
# that happens to share a word — e.g. a page that mentions "advice" or
# a heading literally named "お知らせ" (notices) must survive this.
COOKIE_BANNER_HINTS = [
    "cookie-consent",
    "cookie-banner",
    "cookiebanner",
    "cookie-notice",
    "gdpr-consent",
    "consent-banner",
]
AD_HINTS = [
    "advert",  # catches advertisement/advertising/advert-banner etc.
    "ad-slot",
    "adslot",
    "ad-banner",
    "sponsored",
    "google-ad",
]


def _class_and_id(tag: Tag) -> str:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = [classes]
    return " ".join([*classes, str(tag.get("id") or "")]).lower()


def _looks_like(tag: Tag, hints: list[str]) -> bool:
    haystack = _class_and_id(tag)
    return any(hint in haystack for hint in hints)


def _remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """Mutates `soup` in place, removing elements that never belong in
    analyzable text. Two passes: known noise tags by name, then a
    best-effort class/id heuristic for cookie banners and ad slots
    (which use arbitrary tag names, usually <div>).
    """
    for tag in soup(EXCLUDED_TAGS):
        tag.decompose()

    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        if _looks_like(tag, COOKIE_BANNER_HINTS) or _looks_like(tag, AD_HINTS):
            tag.decompose()


def _normalize_whitespace(text: str) -> str:
    """Collapses runs of whitespace only. Full text normalization
    (full-width/half-width, etc.) is the future Normalizer stage's
    job, not this Cleaner's — see docs/11_architecture_v1.md.
    """
    return " ".join(text.split())


def extract_title(html: str) -> str | None:
    """Best-effort <title> extraction."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        return title or None
    return None


def clean_html_to_text(html: str, source_url: str | None = None) -> str:
    """Extracts analyzable plain text from an HTML document.

    `source_url` is accepted (currently unused) so that future,
    domain-specific cleaning rules have somewhere to hook in without
    another signature change.
    """
    del source_url  # reserved for future domain-specific cleaning rules

    soup = BeautifulSoup(html, "html.parser")
    _remove_unwanted_elements(soup)

    text = soup.get_text(separator=" ", strip=True)
    text = _normalize_whitespace(text)
    return text[:MAX_BODY_TEXT_LENGTH]
