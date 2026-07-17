"""Minimal DataForSEO Sandbox HTTP client, used as the first probe for
whether an AI Overview-type SERP feature can be observed for a brand.

**This module only ever calls DataForSEO Sandbox — never Live.** There
is no code path here that constructs a request against
`services.dataforseo_settings.LIVE_BASE_URL`; only `SANDBOX_BASE_URL`
is used. Whether to call this client at all (based on
`DATAFORSEO_API_ENV`/credentials) is decided by the caller
(services/ai_overview_provider.py), not by this module.

Endpoint choice (see docs/07_decisions.md for the full rationale):

- We call `/v3/serp/google/organic/live/advanced` (DataForSEO's
  "Standard/Live" Google Organic SERP endpoint — "live" here is
  DataForSEO's own naming for their instant-response method, distinct
  from the Sandbox/Live *environment* distinction this codebase cares
  about; we still only ever point it at the Sandbox host). Google
  Organic SERP results already surface an "ai_overview" item type
  inside `items[]` when Google shows an AI Overview for that query,
  with no separate cost tier.
- We deliberately do NOT call `/v3/serp/google/ai_mode/live/advanced`
  (Google's separate "AI Mode" / `udm=50` experience). DataForSEO
  bills that endpoint per request even more aggressively, and Google
  AI Mode is a distinct product from AI Overview — conflating the two
  would misrepresent what "AI Overview比較" is actually measuring.
  This task's own instructions call this endpoint out by name as one
  to avoid.
- DataForSEO's response envelope (`tasks[].result[].items[]`) is
  consistent across their SERP APIs, but the exact shape of an
  `ai_overview` item hasn't been verified against a real Sandbox
  response in this environment (no network access here). The parser
  below is deliberately defensive/best-effort: any unexpected shape is
  treated as "no supported item found" rather than raising.

This client never raises out of `fetch_ai_overview_sandbox()` —
network errors, timeouts, non-2xx responses, and unexpected response
shapes are all caught and converted into a `DataForSEOSandboxResult`
with `success=False` and a safe (credential-free) `reason`, so a
DataForSEO outage or Sandbox quirk can never take down `/analyze`.
"""

import logging
from dataclasses import dataclass

import httpx

from services.dataforseo_settings import SANDBOX_BASE_URL, DataForSEOCredentials

logger = logging.getLogger(__name__)

# Path chosen per the module docstring above — never the ai_mode path.
ORGANIC_LIVE_ADVANCED_PATH = "/v3/serp/google/organic/live/advanced"

# Generous enough for a single Sandbox call, short enough that a
# DataForSEO-side hang can't stall /analyze for long.
REQUEST_TIMEOUT_SECONDS = 12.0

DEFAULT_LOCATION_CODE = 2840  # DataForSEO location_code for "United States"
DEFAULT_LANGUAGE_CODE = "en"

# DataForSEO SERP item "type" values that represent an AI Overview-like
# feature. Matched by substring (case-insensitive) rather than an exact
# literal, since the precise string can't be verified against a real
# Sandbox response in this environment — see module docstring. Does
# NOT include a plain "ai_mode" hint on purpose: this client never
# requests the ai_mode endpoint, so an item merely mentioning "mode"
# elsewhere shouldn't be mistaken for an AI Overview feature.
_AI_OVERVIEW_ITEM_TYPE_HINTS = ("ai_overview",)

_SUMMARY_MAX_CHARS = 200

_DATAFORSEO_SUCCESS_STATUS_CODE = 20000


@dataclass(frozen=True)
class DataForSEOSandboxResult:
    """Outcome of one Sandbox call, already reduced to what
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


def _build_request_body(keyword: str, location_code: int, language_code: str) -> list[dict]:
    return [
        {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
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


def _summarize_item(item: dict, brand_name: str) -> tuple[bool, int | None, str]:
    """Reduces one AI Overview-type item to (mentioned, rank, summary).
    `summary` is always a short excerpt (<= _SUMMARY_MAX_CHARS), never
    the item's full/raw content.
    """
    raw_rank = item.get("rank_absolute")
    rank = raw_rank if isinstance(raw_rank, int) else None

    text_parts: list[str] = []
    raw_text = item.get("text")
    if isinstance(raw_text, str):
        text_parts.append(raw_text)
    nested_items = item.get("items")
    if isinstance(nested_items, list):
        for nested in nested_items:
            if isinstance(nested, dict) and isinstance(nested.get("text"), str):
                text_parts.append(nested["text"])

    joined = " ".join(part.strip() for part in text_parts if part.strip())
    mentioned = brand_name.lower() in joined.lower()

    if not joined:
        summary = "DataForSEO Sandbox returned an AI Overview-type item with no readable text."
    elif len(joined) > _SUMMARY_MAX_CHARS:
        summary = joined[:_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        summary = joined

    return mentioned, rank, summary


def fetch_ai_overview_sandbox(
    credentials: DataForSEOCredentials,
    brand_name: str,
    location_code: int = DEFAULT_LOCATION_CODE,
    language_code: str = DEFAULT_LANGUAGE_CODE,
) -> DataForSEOSandboxResult:
    """Calls DataForSEO Sandbox's Google Organic SERP "live/advanced"
    endpoint for `brand_name` and looks for an AI Overview-type item.
    Always hits SANDBOX_BASE_URL — never the Live host. Issues exactly
    one HTTP request (multi-keyword batching is out of scope for this
    task, so DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE isn't consulted here
    — the current implementation always makes 1 request regardless of
    that setting's configured value).
    """
    url = f"{SANDBOX_BASE_URL}{ORGANIC_LIVE_ADVANCED_PATH}"
    body = _build_request_body(brand_name, location_code, language_code)

    try:
        response = httpx.post(
            url,
            json=body,
            auth=(credentials.login, credentials.password),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("DataForSEO Sandbox request failed (network/timeout error)")
        return DataForSEOSandboxResult(
            success=False,
            reason="DataForSEO Sandbox request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("DataForSEO Sandbox returned HTTP %d", response.status_code)
        return DataForSEOSandboxResult(
            success=False,
            reason=f"DataForSEO Sandbox request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("DataForSEO Sandbox returned a non-JSON response")
        return DataForSEOSandboxResult(
            success=False,
            reason="DataForSEO Sandbox request failed: response was not valid JSON.",
        )

    status_code = payload.get("status_code") if isinstance(payload, dict) else None
    if status_code != _DATAFORSEO_SUCCESS_STATUS_CODE:
        logger.warning("DataForSEO Sandbox response was not successful: status_code=%r", status_code)
        return DataForSEOSandboxResult(
            success=False,
            reason="DataForSEO Sandbox request failed: unexpected response status.",
        )

    item = _extract_ai_overview_item(payload)
    if item is None:
        return DataForSEOSandboxResult(
            success=False,
            reason="DataForSEO Sandbox response received, but no supported AI overview item was found.",
        )

    mentioned, rank, summary = _summarize_item(item, brand_name)
    return DataForSEOSandboxResult(
        success=True,
        reason="DataForSEO Sandbox request succeeded.",
        mentioned=mentioned,
        rank=rank,
        summary=summary,
    )
