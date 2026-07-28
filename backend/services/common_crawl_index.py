"""Common Crawl Index API client — the first slice of Common Crawl
integration (see docs/13_common_crawl_mvp_design.md for the full MVP
design). This module only searches the Index API for a domain's URL
candidates; it does **not** fetch WARC records, extract HTML, build
`Document[]`, or integrate with `/analyze` — those are later steps in
the design doc's 10-step plan.

**This module never decides *whether* Common Crawl search is allowed**
— it has no read of `COMMON_CRAWL_ENABLED` and performs no gating of
its own, mirroring services/dataforseo_client.py's and
services/chatgpt_client.py's "client trusts the caller" design (see
those modules' docstrings for the same rationale). A future
common_crawl_provider.py is expected to read
`CommonCrawlSettings.enabled` before ever calling
`search_common_crawl_domain()` — exactly like
services/ai_overview_provider.py/services/chatgpt_provider.py gate
their respective clients.

Common Crawl's Index API and WARC storage are both public and
unauthenticated — there is no credential type in this module or in
services/common_crawl_settings.py, unlike the DataForSEO/ChatGPT
clients.

This client never raises out of `search_common_crawl_domain()` or
`resolve_common_crawl_index()` — network errors, timeouts, non-2xx
responses, and unexpected response shapes are all caught and converted
into a result with `status="unavailable"` (or `success=False` for the
index resolution step) and a safe `reason`, so a Common Crawl outage or
response-shape quirk can never take down `/analyze` once this is wired
in.

Only bounded, structured data is ever kept — no HTML body, no WARC
body, and no raw Index API response text is retained past this
function call (see `CommonCrawlCandidate`, which deliberately has no
field for either).
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from services.common_crawl_settings import CommonCrawlSettings

logger = logging.getLogger(__name__)

COMMON_CRAWL_HOST = "https://index.commoncrawl.org"
COLLINFO_URL = f"{COMMON_CRAWL_HOST}/collinfo.json"

# Cap on how much of a non-200 response body ever reaches a log line —
# enough to eyeball an error page's gist (e.g. "Service Unavailable",
# a Cloudflare block page's title) without risking a large/binary body
# ending up in logs. Never the full body, and never used for a 200
# response (candidate parsing doesn't log the body at all).
_BODY_PREVIEW_MAX_CHARS = 200

# Explicit request headers for every Common Crawl Index API request
# (search and collinfo.json alike). Added after Render logs showed every
# query variant (see `_build_query_variants`) failing with
# httpx.RemoteProtocolError even with retry and query fallback already in
# place — an explicit Accept and "Connection: close" (in case the
# disconnect is a keep-alive/connection-reuse interaction) are a
# low-risk next step to try before anything heavier like
# `trust_env=False` or a different HTTP client (see
# docs/13_common_crawl_mvp_design.md). None of these headers are secret
# — Common Crawl's Index API is public and unauthenticated.
_INDEX_API_ACCEPT_HEADER = "application/json, text/plain;q=0.9, */*;q=0.8"
_INDEX_API_CONNECTION_HEADER = "close"


def _request_headers(settings: CommonCrawlSettings) -> dict[str, str]:
    """HTTP headers sent with every Common Crawl Index API request.
    `User-Agent` reuses `CommonCrawlSettings.user_agent` — previously
    only used for WARC fetches, now explicit here too instead of the
    Index API request relying on httpx's own default.
    """
    return {
        "User-Agent": settings.user_agent,
        "Accept": _INDEX_API_ACCEPT_HEADER,
        "Connection": _INDEX_API_CONNECTION_HEADER,
    }


# Transport-mode fallback. Added after Render logs showed *every* query
# variant (default-filtered/default-unfiltered/www-unfiltered) exhausting
# all retries with httpx.RemoteProtocolError even with explicit headers
# in place — ruling out query shape and headers alone as the cause, and
# leaving httpx's environment-dependent transport configuration (proxy
# env vars, etc.) as a remaining suspect. `"default"` is httpx.get()'s
# normal behavior (`trust_env` left at its default); `"no-env"` passes
# `trust_env=False` to ignore any HTTP_PROXY/HTTPS_PROXY/etc. environment
# variables Render's process might have set. This is deliberately the
# only difference between the two modes — same headers, same query
# variants, same retry policy — see `_http_get`.
_TRANSPORT_MODE_DEFAULT = "default"
_TRANSPORT_MODE_NO_ENV = "no-env"
_TRANSPORT_MODES = (_TRANSPORT_MODE_DEFAULT, _TRANSPORT_MODE_NO_ENV)


def _http_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    transport_mode: str,
    params: list[tuple[str, str]] | None = None,
) -> httpx.Response:
    """Thin wrapper around `httpx.get()`. The only thing `transport_mode`
    changes is whether `trust_env=False` is passed — everything else
    (headers, timeout, params) is identical between modes.
    """
    if transport_mode == _TRANSPORT_MODE_NO_ENV:
        return httpx.get(url, params=params, headers=headers, timeout=timeout, trust_env=False)
    return httpx.get(url, params=params, headers=headers, timeout=timeout)


# Retry policy for transient Common Crawl request failures. Added after a
# Render deployment showed httpx.RemoteProtocolError ("Server disconnected
# without sending a response") — an abrupt disconnect that happens
# immediately, not after `timeout_seconds` elapses, so raising the timeout
# setting alone can never fix it. Fixed for the MVP (not env-configurable);
# see docs/13_common_crawl_mvp_design.md.
_MAX_ATTEMPTS = 3
# Delay before attempt 2 and before attempt 3, respectively.
_RETRY_DELAYS_SECONDS = (0.5, 1.0)
# A non-200 response is not retried by default (400/404 etc. are almost
# never transient), except these three, which commonly indicate a
# temporary upstream/gateway problem.
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})


def _next_retry_delay(attempt: int) -> float:
    """Delay to wait after a failed `attempt` (1-based) before retrying."""
    return _RETRY_DELAYS_SECONDS[attempt - 1]


# Query-variant fallback for search_common_crawl_domain(). Added after
# Render logs showed the standard (filtered) query exhausting all
# `_MAX_ATTEMPTS` retries with httpx.RemoteProtocolError — i.e. retrying
# the *same* query shape wasn't enough. A simpler query (no filters), and
# then the same simple shape against the domain's "www." variant,
# sometimes succeeds where the original query keeps getting an abrupt
# disconnect. This does not replace retry — each variant still gets its
# own `_MAX_ATTEMPTS` attempts before falling back to the next one.
_QUERY_VARIANT_DEFAULT_FILTERED = "default-filtered"
_QUERY_VARIANT_DEFAULT_UNFILTERED = "default-unfiltered"
_QUERY_VARIANT_WWW_UNFILTERED = "www-unfiltered"


def _build_query_variants(
    normalized_domain: str, max_results: int
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Query variants to try, in order, against the Index API for one
    domain search. Each item is `(variant_name, url_pattern, params)`.
    The "www." variant is skipped when `normalized_domain` already
    starts with "www." (it would just repeat the unfiltered variant
    with a doubled-up "www.www." host).
    """
    url_pattern = f"{normalized_domain}/*"
    variants: list[tuple[str, str, list[tuple[str, str]]]] = [
        (
            _QUERY_VARIANT_DEFAULT_FILTERED,
            url_pattern,
            [
                ("url", url_pattern),
                ("output", "json"),
                ("filter", "status:200"),
                ("filter", "mime:text/html"),
                ("limit", str(max_results)),
            ],
        ),
        (
            _QUERY_VARIANT_DEFAULT_UNFILTERED,
            url_pattern,
            [
                ("url", url_pattern),
                ("output", "json"),
                ("limit", str(max_results)),
            ],
        ),
    ]
    if not normalized_domain.startswith("www."):
        www_url_pattern = f"www.{normalized_domain}/*"
        variants.append(
            (
                _QUERY_VARIANT_WWW_UNFILTERED,
                www_url_pattern,
                [
                    ("url", www_url_pattern),
                    ("output", "json"),
                    ("limit", str(max_results)),
                ],
            )
        )
    return variants


# One label of a DNS hostname: 1-63 chars, alphanumeric/hyphen, not
# starting or ending with a hyphen. A full hostname is 2+ labels
# joined by dots — this is what makes "localhost" (no dot) and bare
# words get rejected by _normalize_domain, alongside anything with a
# disallowed character (scheme separators, whitespace, etc.).
_HOSTNAME_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_HOSTNAME_PATTERN = re.compile(rf"^{_HOSTNAME_LABEL}(\.{_HOSTNAME_LABEL})+$")

# Matches a Common Crawl crawl id, e.g. "CC-MAIN-2026-08" — used to
# pick the actual latest entry out of collinfo.json by (year, week)
# rather than assuming the API always returns entries in a particular
# order.
_CRAWL_INDEX_ID_PATTERN = re.compile(r"^CC-MAIN-(\d{4})-(\d{1,2})$", re.IGNORECASE)


@dataclass(frozen=True)
class CommonCrawlIndexResolution:
    """Outcome of resolving which Common Crawl index id to search
    against — either the configured id as-is, or (when
    CommonCrawlSettings.index == "latest") whichever id collinfo.json
    reports as the newest. Never holds the raw collinfo.json response.
    """

    success: bool
    reason: str
    crawl_index: str | None = None


@dataclass(frozen=True)
class CommonCrawlCandidate:
    """One URL candidate from a Common Crawl Index API search result,
    normalized from the API's JSON Lines (CDXJ-style) response.
    Deliberately holds only bounded metadata — no HTML body, no WARC
    body. `filename`/`offset`/`length` are what a later step would need
    to fetch the actual WARC record; this module does not fetch it.
    """

    url: str
    timestamp: str | None = None
    status: int | None = None
    mime: str | None = None
    digest: str | None = None
    length: int | None = None
    offset: int | None = None
    filename: str | None = None
    crawl_index: str = ""
    source: Literal["common_crawl"] = "common_crawl"


@dataclass(frozen=True)
class CommonCrawlIndexResult:
    """Outcome of one domain search against the Common Crawl Index API.
    `status` mirrors this codebase's existing SectionStatus-shaped
    result types (see DataForSEOSerpResult/ChatGptObservationResult) —
    "real" only when at least one candidate was found and parsed,
    "unavailable" for every failure/empty-result case. "off" is
    included in the type for a future common_crawl_provider.py to use
    when COMMON_CRAWL_ENABLED is false — this module itself never
    returns "off", since it does no enabled-gating of its own (see
    module docstring).
    """

    status: Literal["real", "unavailable", "off"]
    reason: str
    crawl_index: str | None = None
    candidates: tuple[CommonCrawlCandidate, ...] = ()


def _normalize_domain(raw: str) -> str | None:
    """Reduces a user-supplied domain (which may be a bare hostname, a
    full URL, or something malformed/dangerous) down to a lowercase
    hostname suitable for a Common Crawl Index API `url=` query, or
    None if it doesn't look like a usable hostname at all.

    Strips a scheme (`https://...`), any path/query/fragment, and any
    userinfo/port, then validates what's left against a strict
    hostname allow-list (_HOSTNAME_PATTERN) — this rejects anything
    with disallowed characters (spaces, control characters, stray
    scheme-like prefixes such as "javascript:") as well as anything
    with no dot at all (e.g. "localhost").
    """
    text = raw.strip()
    if not text:
        return None

    if "://" in text:
        text = text.split("://", 1)[1]

    text = text.split("/", 1)[0]
    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]
    text = text.rsplit("@", 1)[-1]
    text = text.split(":", 1)[0]
    text = text.lower()

    if not _HOSTNAME_PATTERN.match(text):
        return None
    return text


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_crawl_index_id(raw: object) -> tuple[int, int] | None:
    """Extracts (year, week) from a Common Crawl id string like
    "CC-MAIN-2026-08" for comparison purposes. Returns None for
    anything that doesn't match the expected shape.
    """
    if not isinstance(raw, str):
        return None
    match = _CRAWL_INDEX_ID_PATTERN.match(raw.strip())
    if match is None:
        return None
    year, week = match.groups()
    return int(year), int(week)


def _body_preview(text: str) -> str:
    """Truncates a response body down to a short, log-safe preview —
    never the full body (see `_BODY_PREVIEW_MAX_CHARS`). Used only for
    non-200 responses; a 200 response's body is parsed as candidates
    and never logged at all.
    """
    stripped = text.strip()
    if len(stripped) > _BODY_PREVIEW_MAX_CHARS:
        return stripped[:_BODY_PREVIEW_MAX_CHARS] + "..."
    return stripped


def _fetch_collinfo_response(
    settings: CommonCrawlSettings, headers: dict[str, str], transport_mode: str
) -> tuple[httpx.Response | None, CommonCrawlIndexResolution | None, str | None]:
    """Attempts up to `_MAX_ATTEMPTS` times to fetch collinfo.json under
    one `transport_mode`, retrying a transient transport failure
    (`httpx.TransportError`) or a retryable non-200 status
    (502/503/504), sleeping `_next_retry_delay(attempt)` between
    attempts.

    Returns exactly one of:
    - `(response, None, None)` on a 200 response — JSON parsing is the
      caller's job.
    - `(None, terminal_resolution, None)` for a failure that should
      **not** trigger a transport-mode fallback (a non-transport
      `httpx.HTTPError`, or a non-retryable non-200 status) — the
      caller returns `terminal_resolution` immediately.
    - `(None, None, last_failure_type)` when every attempt under this
      `transport_mode` was exhausted via a transient transport failure
      or a retryable non-200 — eligible for a transport-mode fallback
      (see `_fetch_latest_index`).
    """
    last_error_type: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        logger.info(
            "Common Crawl collinfo.json request start url=%s timeout=%s transport_mode=%s attempt=%d/%d user_agent=%s accept=%s connection=%s",
            COLLINFO_URL,
            settings.timeout_seconds,
            transport_mode,
            attempt,
            _MAX_ATTEMPTS,
            headers["User-Agent"],
            headers["Accept"],
            headers["Connection"],
        )
        try:
            response = _http_get(
                COLLINFO_URL,
                headers=headers,
                timeout=settings.timeout_seconds,
                transport_mode=transport_mode,
            )
        except httpx.TransportError as exc:
            # error_type distinguishes a genuine read timeout
            # (httpx.ReadTimeout/ConnectTimeout) from an immediate failure
            # like DNS resolution/connection refusal (httpx.ConnectError)
            # or an abrupt disconnect (httpx.RemoteProtocolError) — all of
            # which are worth a short retry, since they're often transient.
            last_error_type = exc.__class__.__name__
            logger.warning(
                "Common Crawl collinfo.json request failed transport_mode=%s attempt=%d/%d error_type=%s error=%s",
                transport_mode,
                attempt,
                _MAX_ATTEMPTS,
                exc.__class__.__name__,
                exc,
            )
            if attempt < _MAX_ATTEMPTS:
                delay = _next_retry_delay(attempt)
                logger.info(
                    "Common Crawl collinfo.json request retrying transport_mode=%s next_attempt=%d/%d delay=%s",
                    transport_mode,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.warning(
                "Common Crawl collinfo.json request exhausted retries transport_mode=%s attempts=%d last_error_type=%s",
                transport_mode,
                _MAX_ATTEMPTS,
                last_error_type,
            )
            return None, None, last_error_type
        except httpx.HTTPError as exc:
            # A non-transport HTTPError is not retried, and does not
            # trigger a transport-mode fallback — unexpected and
            # unlikely to be transient or transport-related.
            logger.warning(
                "Common Crawl collinfo.json request failed transport_mode=%s attempt=%d/%d error_type=%s error=%s",
                transport_mode,
                attempt,
                _MAX_ATTEMPTS,
                exc.__class__.__name__,
                exc,
            )
            return (
                None,
                CommonCrawlIndexResolution(
                    success=False,
                    reason="Common Crawl collinfo.json request failed due to a network or timeout error.",
                ),
                None,
            )

        if response.status_code != 200:
            retryable = response.status_code in _RETRYABLE_STATUS_CODES
            logger.warning(
                "Common Crawl collinfo.json returned non-200 transport_mode=%s attempt=%d/%d status=%d body_preview=%s",
                transport_mode,
                attempt,
                _MAX_ATTEMPTS,
                response.status_code,
                _body_preview(response.text),
            )
            if retryable and attempt < _MAX_ATTEMPTS:
                delay = _next_retry_delay(attempt)
                logger.info(
                    "Common Crawl collinfo.json request retrying transport_mode=%s next_attempt=%d/%d delay=%s",
                    transport_mode,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
                continue
            if retryable:
                # Retries on this retryable non-200 status are exhausted
                # for this transport mode — eligible for a transport-mode
                # fallback, same as an exhausted transport error. A
                # non-retryable non-200 (the `else` below) is terminal.
                return None, None, f"HTTP{response.status_code}"
            return (
                None,
                CommonCrawlIndexResolution(
                    success=False,
                    reason=f"Common Crawl collinfo.json request failed with HTTP {response.status_code}.",
                ),
                None,
            )

        if attempt > 1 or transport_mode != _TRANSPORT_MODE_DEFAULT:
            logger.info(
                "Common Crawl collinfo.json request succeeded transport_mode=%s attempt=%d/%d",
                transport_mode,
                attempt,
                _MAX_ATTEMPTS,
            )
        return response, None, None

    # Unreachable: every branch above either `continue`s (only when
    # attempt < _MAX_ATTEMPTS) or returns.
    return None, None, last_error_type


def _fetch_latest_index(settings: CommonCrawlSettings) -> CommonCrawlIndexResolution:
    """Fetches collinfo.json and picks the entry with the greatest
    (year, week) — not just the first entry — so this doesn't depend
    on collinfo.json always being sorted a particular way.

    Tries `_TRANSPORT_MODES` in order (see module docstring above that
    constant) — `"default"` first, falling back to `"no-env"`
    (`trust_env=False`) only if every attempt across every query variant
    under `"default"` was exhausted via a transient transport failure or
    a retryable non-200 (see `_fetch_collinfo_response`). Any other
    failure (a non-transport HTTPError, a non-retryable non-200 status,
    or exhausting every transport mode) still returns `success=False`
    with a safe reason instead of raising.
    """
    headers = _request_headers(settings)
    response: httpx.Response | None = None
    last_failure_type: str | None = None
    for transport_index, transport_mode in enumerate(_TRANSPORT_MODES):
        response, terminal, failure_type = _fetch_collinfo_response(settings, headers, transport_mode)
        if terminal is not None:
            return terminal
        if response is not None:
            break
        last_failure_type = failure_type
        if transport_index < len(_TRANSPORT_MODES) - 1:
            next_mode = _TRANSPORT_MODES[transport_index + 1]
            logger.info(
                "Common Crawl collinfo.json transport fallback from=%s to=%s reason=%s",
                transport_mode,
                next_mode,
                last_failure_type,
            )
            continue
        logger.warning(
            "Common Crawl collinfo.json all transports failed transports=%d last_error_type=%s",
            len(_TRANSPORT_MODES),
            last_failure_type,
        )
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json request failed due to a network or timeout error.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Common Crawl collinfo.json returned a non-JSON response")
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json request failed: response was not valid JSON.",
        )

    if not isinstance(payload, list):
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json response was not a list.",
        )

    best_id: str | None = None
    best_key: tuple[int, int] | None = None
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        key = _parse_crawl_index_id(entry_id)
        if key is None:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_id = entry_id

    if best_id is None:
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json contained no recognizable crawl index id.",
        )

    return CommonCrawlIndexResolution(
        success=True,
        reason="Resolved the latest Common Crawl index from collinfo.json.",
        crawl_index=best_id,
    )


def resolve_common_crawl_index(settings: CommonCrawlSettings) -> CommonCrawlIndexResolution:
    """Decides which Common Crawl index id to search against.

    When `settings.index` is an explicit "CC-MAIN-YYYY-NN" id (already
    validated by services/common_crawl_settings.py), it's used as-is —
    no extra HTTP request is made to confirm it exists, since that
    would be an unnecessary additional external call for the common
    case. Only `settings.index == "latest"` triggers a collinfo.json
    fetch (see `_fetch_latest_index`).
    """
    if settings.index != "latest":
        return CommonCrawlIndexResolution(
            success=True,
            reason="Using the configured Common Crawl index.",
            crawl_index=settings.index,
        )
    return _fetch_latest_index(settings)


def _parse_candidates(
    text: str, crawl_index: str, max_results: int
) -> tuple[CommonCrawlCandidate, ...]:
    """Parses the Index API's JSON Lines (one JSON object per line)
    response body into CommonCrawlCandidate entries, skipping blank
    lines and any line that isn't a parseable JSON object with a
    usable `url`. Stops once `max_results` candidates have been
    collected, regardless of how many lines remain.
    """
    candidates: list[CommonCrawlCandidate] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue

        url = _string_or_none(raw.get("url"))
        if url is None:
            continue

        candidates.append(
            CommonCrawlCandidate(
                url=url,
                timestamp=_string_or_none(raw.get("timestamp")),
                status=_int_or_none(raw.get("status")),
                mime=_string_or_none(raw.get("mime")),
                digest=_string_or_none(raw.get("digest")),
                length=_int_or_none(raw.get("length")),
                offset=_int_or_none(raw.get("offset")),
                filename=_string_or_none(raw.get("filename")),
                crawl_index=crawl_index,
            )
        )
        if len(candidates) >= max_results:
            break

    return tuple(candidates)


def _search_query_variants(
    crawl_index: str,
    normalized_domain: str,
    settings: CommonCrawlSettings,
    headers: dict[str, str],
    transport_mode: str,
) -> tuple[CommonCrawlIndexResult | None, str | None]:
    """Tries every query variant (see `_build_query_variants`) against
    the Index API under one `transport_mode`, each with its own
    `_MAX_ATTEMPTS` retries, falling back to the next variant once a
    variant's attempts are exhausted (see module-level
    `_build_query_variants` docstring).

    Returns `(result, None)` for a *terminal* outcome — success, or a
    failure that should not trigger a transport-mode fallback (a
    non-transport `httpx.HTTPError`, a non-retryable non-200 status, or
    a successful-but-empty result) — the caller returns `result`
    immediately, same as before transport-mode fallback was added.
    Returns `(None, last_failure_type)` when every query variant's
    retries were exhausted via a transient transport failure or a
    retryable non-200 status — eligible for a transport-mode fallback
    (see `search_common_crawl_domain`).
    """
    base_url = f"{COMMON_CRAWL_HOST}/{crawl_index}-index"
    variants = _build_query_variants(normalized_domain, settings.max_results)

    last_failure_type: str | None = None
    for variant_index, (variant_name, url_pattern, params) in enumerate(variants):
        # No secrets here: Common Crawl's Index API is public and
        # unauthenticated (see module docstring).
        request_url = str(httpx.URL(base_url, params=params))
        last_error_type: str | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            # Logged before each attempt so the actually-effective
            # index/timeout (as resolved from CommonCrawlSettings, not
            # just whatever's in the environment), the transport mode
            # and query variant in use, and the exact request URL are
            # always on record — this is what let Render's "request
            # failed (network/timeout error)" log line be root-caused
            # (or ruled out) without needing a code change to reproduce
            # it.
            logger.info(
                "Common Crawl Index API request start index=%s domain=%s transport_mode=%s query_variant=%s url_pattern=%s timeout=%s attempt=%d/%d user_agent=%s accept=%s connection=%s request_url=%s",
                crawl_index,
                normalized_domain,
                transport_mode,
                variant_name,
                url_pattern,
                settings.timeout_seconds,
                attempt,
                _MAX_ATTEMPTS,
                headers["User-Agent"],
                headers["Accept"],
                headers["Connection"],
                request_url,
            )

            try:
                response = _http_get(
                    base_url,
                    params=params,
                    headers=headers,
                    timeout=settings.timeout_seconds,
                    transport_mode=transport_mode,
                )
            except httpx.TransportError as exc:
                # error_type (e.g. "RemoteProtocolError" vs "ReadTimeout"
                # vs "ConnectError") is what distinguishes an abrupt
                # disconnect or immediate connection failure from a
                # genuine read timeout — Render observed
                # RemoteProtocolError ("Server disconnected without
                # sending a response") persisting across all 3 retries of
                # every query variant, which is what motivated trying a
                # transport-mode fallback rather than more query variants.
                last_error_type = exc.__class__.__name__
                logger.warning(
                    "Common Crawl Index API request failed index=%s domain=%s transport_mode=%s query_variant=%s attempt=%d/%d error_type=%s error=%s",
                    crawl_index,
                    normalized_domain,
                    transport_mode,
                    variant_name,
                    attempt,
                    _MAX_ATTEMPTS,
                    exc.__class__.__name__,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    delay = _next_retry_delay(attempt)
                    logger.info(
                        "Common Crawl Index API request retrying index=%s domain=%s transport_mode=%s query_variant=%s next_attempt=%d/%d delay=%s",
                        crawl_index,
                        normalized_domain,
                        transport_mode,
                        variant_name,
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "Common Crawl Index API request exhausted retries index=%s domain=%s transport_mode=%s query_variant=%s attempts=%d last_error_type=%s",
                    crawl_index,
                    normalized_domain,
                    transport_mode,
                    variant_name,
                    _MAX_ATTEMPTS,
                    last_error_type,
                )
                last_failure_type = last_error_type
                break
            except httpx.HTTPError as exc:
                # A non-transport HTTPError is not retried and does not
                # fall back to another query variant or transport mode —
                # unexpected and unlikely to be transient or
                # query-shape/transport-related.
                logger.warning(
                    "Common Crawl Index API request failed index=%s domain=%s transport_mode=%s query_variant=%s attempt=%d/%d error_type=%s error=%s",
                    crawl_index,
                    normalized_domain,
                    transport_mode,
                    variant_name,
                    attempt,
                    _MAX_ATTEMPTS,
                    exc.__class__.__name__,
                    exc,
                )
                return (
                    CommonCrawlIndexResult(
                        status="unavailable",
                        reason="Common Crawl Index API request failed due to a network or timeout error.",
                        crawl_index=crawl_index,
                    ),
                    None,
                )

            if response.status_code != 200:
                retryable = response.status_code in _RETRYABLE_STATUS_CODES
                logger.warning(
                    "Common Crawl Index API returned non-200 index=%s domain=%s transport_mode=%s query_variant=%s attempt=%d/%d status=%d body_preview=%s",
                    crawl_index,
                    normalized_domain,
                    transport_mode,
                    variant_name,
                    attempt,
                    _MAX_ATTEMPTS,
                    response.status_code,
                    _body_preview(response.text),
                )
                if retryable and attempt < _MAX_ATTEMPTS:
                    delay = _next_retry_delay(attempt)
                    logger.info(
                        "Common Crawl Index API request retrying index=%s domain=%s transport_mode=%s query_variant=%s next_attempt=%d/%d delay=%s",
                        crawl_index,
                        normalized_domain,
                        transport_mode,
                        variant_name,
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                if retryable:
                    # Retries on this retryable non-200 status are
                    # exhausted for this variant — fall back to the next
                    # query variant, same as an exhausted transport
                    # error. A non-retryable non-200 (e.g. 400/404, the
                    # `else` below) does not fall back.
                    last_failure_type = f"HTTP{response.status_code}"
                    break
                return (
                    CommonCrawlIndexResult(
                        status="unavailable",
                        reason=f"Common Crawl Index API request failed with HTTP {response.status_code}.",
                        crawl_index=crawl_index,
                    ),
                    None,
                )

            # A 200 response never falls back to another query variant or
            # transport mode — even a successful-but-empty result (see
            # module docstring: whether to broaden the query on zero
            # results is a separate, future consideration from this
            # fallback's purpose of working around a communication
            # failure).
            candidates = _parse_candidates(response.text, crawl_index, settings.max_results)
            if variant_index > 0 or attempt > 1 or transport_mode != _TRANSPORT_MODE_DEFAULT:
                logger.info(
                    "Common Crawl Index API request succeeded index=%s domain=%s transport_mode=%s query_variant=%s attempt=%d/%d candidates=%d",
                    crawl_index,
                    normalized_domain,
                    transport_mode,
                    variant_name,
                    attempt,
                    _MAX_ATTEMPTS,
                    len(candidates),
                )
            if not candidates:
                return (
                    CommonCrawlIndexResult(
                        status="unavailable",
                        reason="Common Crawl index result was empty.",
                        crawl_index=crawl_index,
                    ),
                    None,
                )

            return (
                CommonCrawlIndexResult(
                    status="real",
                    reason=f"Common Crawl Index API request succeeded ({len(candidates)} candidate(s)).",
                    crawl_index=crawl_index,
                    candidates=candidates,
                ),
                None,
            )

        # Reached only via `break` above: this variant's attempts (or its
        # retryable non-200 status) were exhausted. Fall back to the next
        # query variant, if any.
        if variant_index < len(variants) - 1:
            next_variant_name = variants[variant_index + 1][0]
            logger.info(
                "Common Crawl Index API query fallback index=%s domain=%s transport_mode=%s from=%s to=%s reason=%s",
                crawl_index,
                normalized_domain,
                transport_mode,
                variant_name,
                next_variant_name,
                last_failure_type,
            )
            continue

        logger.warning(
            "Common Crawl Index API all query variants failed index=%s domain=%s transport_mode=%s variants=%d last_error_type=%s",
            crawl_index,
            normalized_domain,
            transport_mode,
            len(variants),
            last_failure_type,
        )
        return None, last_failure_type

    # Unreachable: `variants` always has at least 2 entries, and every
    # variant's inner loop either returns or breaks into the
    # fallback/final-failure handling above.
    return None, last_failure_type


def search_common_crawl_domain(domain: str, settings: CommonCrawlSettings) -> CommonCrawlIndexResult:
    """Searches the Common Crawl Index API for URLs under `domain`
    (e.g. "cybozu.co.jp"), restricted to successful (`status:200`) HTML
    (`mime:text/html`) captures, capped at `settings.max_results`.

    This function itself does not decide whether calling Common Crawl
    is *allowed* — see the module docstring: any `COMMON_CRAWL_ENABLED`
    gating belongs to a future provider layer, not here.

    Tries `_TRANSPORT_MODES` in order (see module docstring above that
    constant) — `"default"` first, falling back to `"no-env"`
    (`trust_env=False`) only if every query variant's every attempt
    under `"default"` was exhausted via a transient transport failure
    (`httpx.TransportError` — RemoteProtocolError, ConnectError,
    ReadTimeout, etc.) or a retryable non-200 status (502/503/504) —
    see `_search_query_variants`. A non-transport `httpx.HTTPError`, a
    non-retryable non-200 status (e.g. 400/404), or a
    successful-but-empty result does **not** fall back to another
    query variant or transport mode — those return
    `status="unavailable"` immediately, same as before this fallback
    was added. Every failure path still returns a
    `CommonCrawlIndexResult` with `status="unavailable"` and a safe,
    credential-free `reason` instead of raising (there are no
    credentials to leak in the first place, since Common Crawl is a
    public, unauthenticated dataset).
    """
    normalized_domain = _normalize_domain(domain)
    if normalized_domain is None:
        return CommonCrawlIndexResult(
            status="unavailable",
            reason="Common Crawl domain is empty or not a valid hostname.",
        )

    resolution = resolve_common_crawl_index(settings)
    if not resolution.success:
        return CommonCrawlIndexResult(status="unavailable", reason=resolution.reason)

    crawl_index = resolution.crawl_index or ""
    headers = _request_headers(settings)

    last_failure_type: str | None = None
    for transport_index, transport_mode in enumerate(_TRANSPORT_MODES):
        result, failure_type = _search_query_variants(
            crawl_index, normalized_domain, settings, headers, transport_mode
        )
        if result is not None:
            return result
        last_failure_type = failure_type
        if transport_index < len(_TRANSPORT_MODES) - 1:
            next_mode = _TRANSPORT_MODES[transport_index + 1]
            logger.info(
                "Common Crawl Index API transport fallback index=%s domain=%s from=%s to=%s reason=%s",
                crawl_index,
                normalized_domain,
                transport_mode,
                next_mode,
                last_failure_type,
            )
            continue

        logger.warning(
            "Common Crawl Index API all transports failed index=%s domain=%s transports=%d last_error_type=%s",
            crawl_index,
            normalized_domain,
            len(_TRANSPORT_MODES),
            last_failure_type,
        )
        return CommonCrawlIndexResult(
            status="unavailable",
            reason="Common Crawl Index API request failed due to a network or timeout error.",
            crawl_index=crawl_index,
        )

    # Unreachable: `_TRANSPORT_MODES` always has at least 1 entry, and
    # every mode's query-variant loop either returns or continues into
    # the transport-fallback/final-failure handling above.
    return CommonCrawlIndexResult(
        status="unavailable",
        reason="Common Crawl Index API request failed due to a network or timeout error.",
        crawl_index=crawl_index,
    )
