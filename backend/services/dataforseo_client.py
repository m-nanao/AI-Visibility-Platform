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

_DATAFORSEO_SUCCESS_STATUS_CODE = 20000

# Markdown link/image syntax makes for a noisy summary excerpt to a
# human reader; before truncating we lightly flatten the two most
# common forms rather than showing raw "![alt](url)"/"[text](url)".
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")


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


def _summarize_item(item: dict, brand_name: str) -> tuple[bool, int | None, str]:
    """Reduces one AI Overview-type item to (mentioned, rank, summary).
    `summary` is always a short excerpt (<= _SUMMARY_MAX_CHARS), never
    the item's full/raw content (references are not included — see
    docs/07_decisions.md for why the reference list isn't surfaced).
    """
    raw_rank = item.get("rank_absolute")
    if not isinstance(raw_rank, int):
        raw_rank = item.get("rank_group")
    rank = raw_rank if isinstance(raw_rank, int) else None

    mentioned = brand_name.lower() in _collect_mentioned_check_text(item).lower()

    # markdown is preferred (the AI Mode endpoint's primary content
    # field); "text" is the fallback used by the Organic endpoint's
    # ai_overview item shape.
    summary_source_parts = _text_fields(item, "markdown") or _text_fields(item, "text")
    if not summary_source_parts:
        nested_items = item.get("items")
        if isinstance(nested_items, list):
            for nested in nested_items:
                summary_source_parts.extend(_text_fields(nested, "markdown", "text"))

    joined = _clean_markdown(" ".join(summary_source_parts))

    if not joined:
        summary = "DataForSEO returned an AI Overview-type item with no readable text."
    elif len(joined) > _SUMMARY_MAX_CHARS:
        summary = joined[:_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        summary = joined

    return mentioned, rank, summary


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

    mentioned, rank, summary = _summarize_item(item, brand_name)
    return DataForSEOSerpResult(
        success=True,
        reason=f"DataForSEO {env_label} {endpoint_label} request succeeded.",
        mentioned=mentioned,
        rank=rank,
        summary=summary,
    )
