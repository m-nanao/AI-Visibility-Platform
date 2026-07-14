"""Fetches and extracts body text from a small number of public URLs.

This is intentionally minimal:

- Each URL is fetched with a timeout; a failure on one URL never
  aborts the rest of the batch (each result reports its own
  success/failure).
- URLs are fetched concurrently, up to MAX_CONCURRENT_FETCHES at a
  time, rather than one after another — see fetch_url_texts().
- Non-http(s) schemes, localhost, and private/loopback/link-local/
  reserved IP addresses are rejected before any request is made, to
  reduce SSRF risk. Redirects are not followed, since a redirect is a
  common way to bypass an initial URL check.
- <script>/<style>/<nav>/<footer>/etc. are stripped before extracting
  text, and the extracted text is capped in length.

What this does NOT do (see docs/07_decisions.md for the reasoning and
docs/05_tasks.md for the follow-up tasks):

- It does not check robots.txt or any site's terms of service. Callers
  of this API are responsible for only pointing it at pages they have
  the right to fetch, and for not using it to scrape at a volume/rate
  that could be considered abusive.
- It does not rate-limit or add politeness delays between requests.
- The SSRF check re-resolves DNS at request time but does not defend
  against DNS being changed between the check and the actual request
  (TOCTOU rebinding). This is a known gap for a future hardening pass.
"""

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

FETCH_TIMEOUT_SECONDS = 5.0
MAX_BODY_TEXT_LENGTH = 5000

# Fetches run concurrently (not one-by-one) so that up to MAX_URLS
# (see models.py) pages don't take MAX_URLS * FETCH_TIMEOUT_SECONDS in
# the worst case. Kept deliberately low (a plain ThreadPoolExecutor,
# no retry/backoff/queueing) to stay simple and to avoid hammering a
# single target site too hard.
MAX_CONCURRENT_FETCHES = 3

# Elements that are never part of the "body text" we want to analyze.
EXCLUDED_TAGS = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "template",
    "form",
    "iframe",
]

USER_AGENT = "LLMO-AI-Visibility-Platform/0.1 (development; +https://github.com/m-nanao/AI-Visibility-Platform)"


@dataclass
class UrlFetchResult:
    url: str
    success: bool
    text: str = ""
    error: str | None = None


def _is_safe_url(url: str) -> tuple[bool, str | None]:
    """Checks a URL is http(s) and doesn't resolve to a disallowed address.

    Returns (is_safe, reason) — reason is None when is_safe is True.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported scheme: {parsed.scheme!r}"

    hostname = parsed.hostname
    if not hostname:
        return False, "missing hostname"

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"could not resolve hostname: {exc}"

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"resolves to a disallowed address: {ip_str}"

    return True, None


def _extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(EXCLUDED_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    return text[:MAX_BODY_TEXT_LENGTH]


def _fetch_one(url: str) -> UrlFetchResult:
    is_safe, reason = _is_safe_url(url)
    if not is_safe:
        return UrlFetchResult(url=url, success=False, error=reason)

    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return UrlFetchResult(url=url, success=False, error=str(exc))

    text = _extract_body_text(response.text)
    return UrlFetchResult(url=url, success=True, text=text)


def fetch_url_texts(urls: list[str]) -> list[UrlFetchResult]:
    """Fetches each URL and extracts its body text.

    Runs up to MAX_CONCURRENT_FETCHES fetches at a time (not fully
    sequential, not fully parallel). A failure fetching one URL is
    recorded in its own result and does not stop the rest of the batch
    from being processed. Results are returned in the same order as
    `urls`, regardless of which finished first.
    """
    if not urls:
        return []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES) as executor:
        return list(executor.map(_fetch_one, urls))
