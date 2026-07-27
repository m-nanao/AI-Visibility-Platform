"""DataForSEO HTTP client, used as the probe for whether an AI
Overview-type SERP feature can be observed for a brand — against
either DataForSEO Sandbox (the default, always-safe path) or, only for
a deliberate one-off manual check, DataForSEO Live.

**This module never decides *whether* to call Live — only *how*.**
Which host a given call actually reaches is controlled entirely by the
`api_env` argument the caller passes in; this module has no env-var
reads and no gating logic of its own. All of the actual safety
gating — whether `api_env="live"` is even reachable at all — lives in
services/ai_overview_provider.py's `_run_dataforseo_mode()`, which only
ever passes `api_env="live"` after confirming
`DataForSEOSettings.is_live_allowed_for_manual_check` is `True` (all
five independent env-var gates satisfied at once; see
services/dataforseo_settings.py and docs/07_decisions.md). This module
being simple and gate-free is intentional: a single, thoroughly-tested
gate in one place is safer than duplicating gate logic across two
modules that could drift out of sync.

Endpoint choice (see docs/07_decisions.md for the full rationale,
updated after manual verification against DataForSEO Sandbox):

- The default and recommended endpoint is
  `/v3/serp/google/ai_mode/live/advanced` (`google_ai_mode_live_advanced`
  — DataForSEO's naming for Google's separate "AI Mode" experience).
  Manually querying DataForSEO Sandbox for "Vercel" with
  `location_code=2392` (Japan), `language_code=ja`, `device=desktop`,
  `os=windows` against this endpoint reliably returned an
  `item_types: ["ai_overview"]` result with `items[0].type ==
  "ai_overview"`, `items[0].markdown`, and `items[0].references`. The
  same manual check against `/v3/serp/google/organic/live/advanced`
  (`google_organic_live_advanced`) did not reliably surface an
  `ai_overview` item, so it is kept only as a backwards-compatible
  fallback (`DATAFORSEO_SERP_ENDPOINT=google_organic_live_advanced`),
  not the default.
- "live" in both endpoint names is DataForSEO's own naming for their
  instant-response request method (as opposed to their asynchronous
  `task_post`/`task_get` "Standard" method) — orthogonal to the
  Sandbox/Live *environment* distinction (`DATAFORSEO_API_ENV`) this
  codebase cares about. This applies equally to a Sandbox call (the
  common case) and a manually-gated Live call — the endpoint path is
  the same either way; only the host differs (see `_ENV_BASE_URLS`).
- Google AI Overview and Google AI Mode are still understood to be
  distinct Google features/products; this module reports whichever one
  DataForSEO's chosen endpoint actually returns, and the AI Mode
  endpoint's `ai_overview`-typed item is treated as functionally
  equivalent to "an AI Overview-style answer was found" for this
  MVP's comparison purposes. See `_ENDPOINT_LABELS` below for how each
  endpoint is described in `reason` text and `ai_overview_provider.py`
  for how it's labeled in `AIOverviewComparisonItem.platform`.
- DataForSEO's outer response envelope (`tasks[].result[].items[]`) is
  consistent across their SERP APIs; the parser below is deliberately
  defensive/best-effort about the *item*'s own shape (which does vary
  somewhat by endpoint) — any unexpected shape is treated as "no
  supported item found" rather than raising.
- `references[]`/`links[]` (both the item's own and any nested
  `items[]`'s) are extracted into `DataForSEOSerpResult.references` —
  deduplicated by url (or by domain+title when no url is present) and
  capped at `_MAX_REFERENCES` entries. This is a bounded, structured
  subset (title/domain/url/text/source/position — see
  `DataForSEOSerpReference`), never the raw reference/link dict as
  DataForSEO returned it.

This client never raises out of `fetch_ai_overview_serp()` — network
errors, timeouts, non-2xx responses, and unexpected response shapes
are all caught and converted into a `DataForSEOSerpResult` with
`success=False` and a safe (credential-free) `reason`, so a DataForSEO
outage or response-shape quirk can never take down `/analyze`.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from services.dataforseo_settings import (
    DEFAULT_DEVICE,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_LOCATION_CODE,
    DEFAULT_OS,
    DEFAULT_SERP_ENDPOINT,
    LIVE_BASE_URL,
    SANDBOX_BASE_URL,
    DataForSEOApiEnv,
    DataForSEOCredentials,
    DataForSEOSerpEndpoint,
)

logger = logging.getLogger(__name__)

# Which host each DataForSEO API environment resolves to. Note that
# *this* dict, not any per-call decision in fetch_ai_overview_serp()
# itself, is the only place a request could ever be pointed at the Live
# host — and the caller (services/ai_overview_provider.py) never passes
# api_env="live" unless DataForSEOSettings.is_live_allowed_for_manual_check
# is True.
_ENV_BASE_URLS: dict[DataForSEOApiEnv, str] = {
    "sandbox": SANDBOX_BASE_URL,
    "live": LIVE_BASE_URL,
}
_ENV_LABELS: dict[DataForSEOApiEnv, str] = {
    "sandbox": "Sandbox",
    "live": "Live",
}

# One path per DataForSEOSerpEndpoint value — see module docstring for
# why "google_ai_mode_live_advanced" is the recommended default.
AI_MODE_LIVE_ADVANCED_PATH = "/v3/serp/google/ai_mode/live/advanced"
ORGANIC_LIVE_ADVANCED_PATH = "/v3/serp/google/organic/live/advanced"
_ENDPOINT_PATHS: dict[DataForSEOSerpEndpoint, str] = {
    "google_ai_mode_live_advanced": AI_MODE_LIVE_ADVANCED_PATH,
    "google_organic_live_advanced": ORGANIC_LIVE_ADVANCED_PATH,
}
# Human-readable label per endpoint, used only in `reason` text (never
# in logs/responses alongside credentials).
_ENDPOINT_LABELS: dict[DataForSEOSerpEndpoint, str] = {
    "google_ai_mode_live_advanced": "AI Mode",
    "google_organic_live_advanced": "Organic",
}

# Generous enough for a single Sandbox call, short enough that a
# DataForSEO-side hang can't stall /analyze for long.
REQUEST_TIMEOUT_SECONDS = 12.0

# DataForSEO SERP item "type" values that represent an AI Overview-like
# feature. Matched by substring (case-insensitive) rather than an exact
# literal, since it's cheap insurance against minor naming variants
# across endpoints/DataForSEO API versions.
_AI_OVERVIEW_ITEM_TYPE_HINTS = ("ai_overview",)

_SUMMARY_MAX_CHARS = 200
# fullSummary is a detail view, not an excerpt, so it's allowed much
# more room than _SUMMARY_MAX_CHARS — but still capped well below
# DataForSEO's own item size so a single item can't blow up the
# response body.
_FULL_SUMMARY_MAX_CHARS = 2500
# Reference lists from DataForSEO can be long; capped to keep the
# response small and the UI list readable (see AIOverviewComparisonSection.tsx).
_MAX_REFERENCES = 10

_DATAFORSEO_SUCCESS_STATUS_CODE = 20000

# Markdown link/image syntax makes for a noisy summary excerpt to a
# human reader; before truncating we lightly flatten the two most
# common forms rather than showing raw "![alt](url)"/"[text](url)".
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Collapses 3+ consecutive newlines (i.e. 2+ blank lines) down to a
# single blank line, for fullSummary's lighter-touch cleanup (unlike
# the short summary excerpt, fullSummary keeps paragraph breaks).
_EXCESS_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class DataForSEOSerpReference:
    """One citation/link extracted from a DataForSEO AI Overview-type
    item's `references[]`/`links[]` (including nested `items[]`'s own).
    Every field is optional since DataForSEO's `ai_overview_reference`
    and `link_element` shapes don't carry the same fields (see
    _reference_from_dict).
    """

    title: str | None = None
    domain: str | None = None
    url: str | None = None
    text: str | None = None
    source: str | None = None
    position: str | None = None


@dataclass(frozen=True)
class DataForSEOSerpResult:
    """Outcome of one Sandbox-or-Live call, already reduced to what
    ai_overview_provider.py needs — never holds the raw JSON response
    or any credential. `reason` is always a complete, safe-to-surface
    sentence (see module docstring); `success` is True only when a
    usable AI Overview-type item was actually found and parsed.
    """

    success: bool
    reason: str
    mentioned: bool = False
    rank: int | None = None
    summary: str | None = None
    full_summary: str | None = None
    references: tuple[DataForSEOSerpReference, ...] = ()


def _build_request_body(
    keyword: str, location_code: int, language_code: str, device: str, os_name: str
) -> list[dict]:
    return [
        {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "device": device,
            "os": os_name,
        }
    ]


def _extract_ai_overview_item(payload: object) -> dict | None:
    """Best-effort, defensive walk through DataForSEO's response
    envelope (`tasks[].result[].items[]`) looking for an AI
    Overview-like item. Returns None if the envelope doesn't look like
    what we expect, or no such item is present — both are treated the
    same by the caller ("no supported item found").
    """
    if not isinstance(payload, dict):
        return None

    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return None

    for task in tasks:
        if not isinstance(task, dict):
            continue
        results = task.get("result")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            items = result.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").lower()
                if any(hint in item_type for hint in _AI_OVERVIEW_ITEM_TYPE_HINTS):
                    return item
    return None


def _clean_markdown(text: str) -> str:
    """Lightly flattens markdown image/link syntax so a summary excerpt
    doesn't show raw "![alt](url)"/"[text](url)" noise. Not a full
    markdown renderer — just enough to make the excerpt readable.
    """
    without_images = _MARKDOWN_IMAGE_PATTERN.sub("", text)
    without_links = _MARKDOWN_LINK_PATTERN.sub(r"\1", without_images)
    return re.sub(r"\s+", " ", without_links).strip()


def _clean_markdown_for_full_summary(text: str) -> str:
    """Like _clean_markdown, but for fullSummary: keeps paragraph breaks
    (only collapses 2+ blank lines down to one) instead of flattening
    all whitespace to a single space, so the detail view still reads as
    paragraphs rather than one long line.
    """
    without_images = _MARKDOWN_IMAGE_PATTERN.sub("", text)
    without_links = _MARKDOWN_LINK_PATTERN.sub(r"\1", without_images)
    collapsed_blank_lines = _EXCESS_BLANK_LINES_PATTERN.sub("\n\n", without_links)
    lines = [line.rstrip() for line in collapsed_blank_lines.splitlines()]
    return "\n".join(lines).strip()


def _text_fields(source: object, *field_names: str) -> list[str]:
    """Pulls out the given string-valued fields from `source` if it's a
    dict, ignoring any that are missing or not strings.
    """
    if not isinstance(source, dict):
        return []
    parts = []
    for name in field_names:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return parts


def _collect_mentioned_check_text(item: dict) -> str:
    """Gathers every text field that plausibly contains the brand name
    somewhere in the item, across the shapes seen from both the AI Mode
    and Organic endpoints: the item's own markdown/text, nested
    `items[]` (markdown/text), and `references[]` (title/text/domain).
    Used only to decide `mentioned` — not shown to the caller.
    """
    parts = _text_fields(item, "markdown", "text")

    nested_items = item.get("items")
    if isinstance(nested_items, list):
        for nested in nested_items:
            parts.extend(_text_fields(nested, "markdown", "text"))

    references = item.get("references")
    if isinstance(references, list):
        for reference in references:
            parts.extend(_text_fields(reference, "title", "text", "domain"))

    return " ".join(parts)


def _gather_summary_source_parts(item: dict) -> list[str]:
    """Collects the text parts both `summary` and `fullSummary` are
    built from: the item's own markdown (preferred) or text (fallback —
    the Organic endpoint's ai_overview item shape uses this), or, if
    neither is present, every nested `items[]`'s markdown/text.
    """
    parts = _text_fields(item, "markdown") or _text_fields(item, "text")
    if not parts:
        nested_items = item.get("items")
        if isinstance(nested_items, list):
            for nested in nested_items:
                parts.extend(_text_fields(nested, "markdown", "text"))
    return parts


def _build_full_summary(parts: list[str]) -> str | None:
    """Builds the fullSummary field from the same source parts as the
    short summary excerpt, but with lighter cleanup (paragraph breaks
    kept, see _clean_markdown_for_full_summary) and a much higher
    length cap (_FULL_SUMMARY_MAX_CHARS). Returns None when there's no
    readable text at all, so AIOverviewComparisonItem.fullSummary stays
    unset rather than an empty string.
    """
    joined = "\n\n".join(part.strip() for part in parts if part.strip())
    if not joined:
        return None

    cleaned = _clean_markdown_for_full_summary(joined)
    if not cleaned:
        return None

    if len(cleaned) > _FULL_SUMMARY_MAX_CHARS:
        return cleaned[:_FULL_SUMMARY_MAX_CHARS].rstrip() + "…"
    return cleaned


def _reference_from_dict(raw: dict) -> DataForSEOSerpReference | None:
    """Converts one raw `references[]`/`links[]` entry (either
    DataForSEO's `ai_overview_reference` shape — source/domain/url/
    title/text/position — or its `link_element` shape —
    title/description/url/domain) into a DataForSEOSerpReference.
    Returns None if the entry has no usable field at all.
    """

    def _string_or_none(value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    title = _string_or_none(raw.get("title"))
    domain = _string_or_none(raw.get("domain"))
    url = _string_or_none(raw.get("url"))
    # link_element entries use "description" where ai_overview_reference
    # entries use "text" — both map to DataForSEOSerpReference.text.
    text = _string_or_none(raw.get("text")) or _string_or_none(raw.get("description"))
    source = _string_or_none(raw.get("source"))
    position = _string_or_none(raw.get("position"))

    if not any([title, domain, url, text]):
        return None

    return DataForSEOSerpReference(
        title=title, domain=domain, url=url, text=text, source=source, position=position
    )


def _collect_references(item: dict) -> tuple[DataForSEOSerpReference, ...]:
    """Gathers references from every shape DataForSEO's AI Overview-type
    items are known to carry them in, in this priority order:
    item.references[], nested items[].references[], nested
    items[].links[], item.links[]. Deduplicates by url (or by
    domain+title when a reference has no url) and caps the result at
    _MAX_REFERENCES.
    """
    raw_candidates: list[dict] = []

    top_references = item.get("references")
    if isinstance(top_references, list):
        raw_candidates.extend(r for r in top_references if isinstance(r, dict))

    nested_items = item.get("items")
    nested_items = nested_items if isinstance(nested_items, list) else []

    for nested in nested_items:
        if not isinstance(nested, dict):
            continue
        nested_references = nested.get("references")
        if isinstance(nested_references, list):
            raw_candidates.extend(r for r in nested_references if isinstance(r, dict))

    for nested in nested_items:
        if not isinstance(nested, dict):
            continue
        nested_links = nested.get("links")
        if isinstance(nested_links, list):
            raw_candidates.extend(r for r in nested_links if isinstance(r, dict))

    top_links = item.get("links")
    if isinstance(top_links, list):
        raw_candidates.extend(r for r in top_links if isinstance(r, dict))

    references: list[DataForSEOSerpReference] = []
    seen_keys: set[str] = set()
    for raw in raw_candidates:
        reference = _reference_from_dict(raw)
        if reference is None:
            continue

        dedup_key = reference.url or f"domain:{reference.domain}|title:{reference.title}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        references.append(reference)
        if len(references) >= _MAX_REFERENCES:
            break

    return tuple(references)


def _summarize_item(
    item: dict, brand_name: str
) -> tuple[bool, int | None, str, str | None, tuple[DataForSEOSerpReference, ...]]:
    """Reduces one AI Overview-type item to (mentioned, rank, summary,
    full_summary, references). `summary` is always a short excerpt
    (<= _SUMMARY_MAX_CHARS); `full_summary` is the fuller text (<=
    _FULL_SUMMARY_MAX_CHARS, may be None if there's no readable text);
    `references` is a bounded, deduplicated list (see
    _collect_references) — never the item's raw/full content.
    """
    raw_rank = item.get("rank_absolute")
    if not isinstance(raw_rank, int):
        raw_rank = item.get("rank_group")
    rank = raw_rank if isinstance(raw_rank, int) else None

    mentioned = brand_name.lower() in _collect_mentioned_check_text(item).lower()

    summary_source_parts = _gather_summary_source_parts(item)
    joined = _clean_markdown(" ".join(summary_source_parts))

    if not joined:
        summary = "DataForSEO returned an AI Overview-type item with no readable text."
    elif len(joined) > _SUMMARY_MAX_CHARS:
        summary = joined[:_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        summary = joined

    full_summary = _build_full_summary(summary_source_parts)
    references = _collect_references(item)

    return mentioned, rank, summary, full_summary, references


def fetch_ai_overview_serp(
    credentials: DataForSEOCredentials,
    brand_name: str,
    *,
    api_env: DataForSEOApiEnv = "sandbox",
    endpoint: DataForSEOSerpEndpoint = DEFAULT_SERP_ENDPOINT,
    location_code: int = DEFAULT_LOCATION_CODE,
    language_code: str = DEFAULT_LANGUAGE_CODE,
    device: str = DEFAULT_DEVICE,
    os_name: str = DEFAULT_OS,
) -> DataForSEOSerpResult:
    """Calls DataForSEO's chosen SERP "live/advanced" endpoint for
    `brand_name` and looks for an AI Overview-type item, against
    whichever host `api_env` selects (`SANDBOX_BASE_URL` for
    `"sandbox"`, `LIVE_BASE_URL` for `"live"`). Issues exactly one HTTP
    request regardless of `api_env` (multi-keyword batching is out of
    scope, so `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE` isn't consulted
    here).

    This function itself does not decide whether `api_env="live"` is
    *allowed* — see the module docstring: that gating lives entirely in
    services/ai_overview_provider.py, which only ever passes
    `api_env="live"` once `DataForSEOSettings.is_live_allowed_for_manual_check`
    is confirmed `True`.

    On success, the returned result also carries `full_summary` (a
    longer, still-bounded excerpt — see `_build_full_summary`) and
    `references` (a deduplicated, capped list — see
    `_collect_references`), in addition to the existing short `summary`.
    """
    env_label = _ENV_LABELS[api_env]
    endpoint_label = _ENDPOINT_LABELS[endpoint]
    url = f"{_ENV_BASE_URLS[api_env]}{_ENDPOINT_PATHS[endpoint]}"
    body = _build_request_body(brand_name, location_code, language_code, device, os_name)

    try:
        response = httpx.post(
            url,
            json=body,
            auth=(credentials.login, credentials.password),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("DataForSEO %s request failed (network/timeout error)", env_label)
        return DataForSEOSerpResult(
            success=False,
            reason=f"DataForSEO {env_label} request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("DataForSEO %s returned HTTP %d", env_label, response.status_code)
        return DataForSEOSerpResult(
            success=False,
            reason=f"DataForSEO {env_label} request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("DataForSEO %s returned a non-JSON response", env_label)
        return DataForSEOSerpResult(
            success=False,
            reason=f"DataForSEO {env_label} request failed: response was not valid JSON.",
        )

    status_code = payload.get("status_code") if isinstance(payload, dict) else None
    if status_code != _DATAFORSEO_SUCCESS_STATUS_CODE:
        logger.warning("DataForSEO %s response was not successful: status_code=%r", env_label, status_code)
        return DataForSEOSerpResult(
            success=False,
            reason=f"DataForSEO {env_label} request failed: unexpected response status.",
        )

    item = _extract_ai_overview_item(payload)
    if item is None:
        return DataForSEOSerpResult(
            success=False,
            reason=(
                f"DataForSEO {env_label} response received, but no ai_overview item "
                f"was found. endpoint={endpoint}"
            ),
        )

    mentioned, rank, summary, full_summary, references = _summarize_item(item, brand_name)
    return DataForSEOSerpResult(
        success=True,
        reason=f"DataForSEO {env_label} {endpoint_label} request succeeded.",
        mentioned=mentioned,
        rank=rank,
        summary=summary,
        full_summary=full_summary,
        references=references,
    )
