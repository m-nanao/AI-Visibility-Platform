"""Reads Common Crawl-related environment variables into a small,
safe-to-pass-around settings object.

This module does not call Common Crawl itself — see
services/common_crawl_index.py for the Index API client. Common Crawl
is a public dataset with no authentication, so unlike
services/dataforseo_settings.py / services/chatgpt_settings.py there is
no credential type here at all; nothing in this module is ever a
secret, so it is safe to log or include in a repr().

See docs/13_common_crawl_mvp_design.md for the full MVP design this
implements the first slice of (settings + Index API search only — no
WARC/HTML fetch, no Document[] conversion, no /analyze integration, no
UI yet).
"""

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_ENABLED = False

DEFAULT_INDEX = "latest"
# Matches Common Crawl's own crawl id format, e.g. "CC-MAIN-2026-08".
# Case-insensitive on input; the resolved value is normalized to this
# canonical (uppercase "CC-MAIN") casing.
_CRAWL_INDEX_ID_PATTERN = re.compile(r"^CC-MAIN-(\d{4})-(\d{1,2})$", re.IGNORECASE)

DEFAULT_MAX_RESULTS = 5
MIN_MAX_RESULTS = 1
MAX_MAX_RESULTS = 10

DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 3.0
MAX_TIMEOUT_SECONDS = 30.0

DEFAULT_USER_AGENT = "AI-Visibility-Platform-MVP"
# Generous but bounded — a User-Agent header has no reason to be huge;
# this is purely a defensive cap against a misconfigured env var, not a
# protocol requirement.
MAX_USER_AGENT_LENGTH = 200

# Common Crawl's Index API is unreliable in practice (observed both
# manually and in Render logs: the same query can 504 or succeed on
# consecutive attempts). Common Crawl is supplementary data for the
# synchronous /analyze request, so the whole Index API search (retries,
# query-variant fallback, transport fallback, and — separately —
# collinfo.json resolution when COMMON_CRAWL_INDEX=latest) is capped by
# this wall-clock budget instead of being allowed to run unbounded.
DEFAULT_INDEX_BUDGET_SECONDS = 8.0
MIN_INDEX_BUDGET_SECONDS = 3.0
MAX_INDEX_BUDGET_SECONDS = 20.0


@dataclass(frozen=True)
class CommonCrawlSettings:
    """Snapshot of Common Crawl configuration for the current process.
    Every field here is safe to log — Common Crawl's Index API and WARC
    files are public and unauthenticated, so there is no credential
    type to keep separate (contrast with DataForSEOSettings/
    ChatGptSettings, which both split out a *Credentials type for the
    one secret each of those providers needs).
    """

    enabled: bool
    index: str
    max_results: int
    timeout_seconds: float
    user_agent: str
    index_budget_seconds: float = DEFAULT_INDEX_BUDGET_SECONDS


def _resolve_enabled() -> bool:
    raw = os.environ.get("COMMON_CRAWL_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_index() -> str:
    raw = os.environ.get("COMMON_CRAWL_INDEX", DEFAULT_INDEX).strip()
    if not raw or raw.lower() == "latest":
        return DEFAULT_INDEX

    match = _CRAWL_INDEX_ID_PATTERN.match(raw)
    if match is None:
        logger.warning(
            "COMMON_CRAWL_INDEX=%r is not \"latest\" or a CC-MAIN-YYYY-NN id; falling back to %r",
            raw,
            DEFAULT_INDEX,
        )
        return DEFAULT_INDEX

    year, week = match.groups()
    return f"CC-MAIN-{year}-{week}"


def _resolve_max_results() -> int:
    raw = os.environ.get("COMMON_CRAWL_MAX_RESULTS", str(DEFAULT_MAX_RESULTS)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "COMMON_CRAWL_MAX_RESULTS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_MAX_RESULTS,
        )
        return DEFAULT_MAX_RESULTS

    if value < MIN_MAX_RESULTS or value > MAX_MAX_RESULTS:
        logger.warning(
            "COMMON_CRAWL_MAX_RESULTS=%d is outside the allowed range [%d, %d]; falling back to %d",
            value,
            MIN_MAX_RESULTS,
            MAX_MAX_RESULTS,
            DEFAULT_MAX_RESULTS,
        )
        return DEFAULT_MAX_RESULTS

    return value


def _resolve_timeout_seconds() -> float:
    raw = os.environ.get("COMMON_CRAWL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "COMMON_CRAWL_TIMEOUT_SECONDS=%r is not a number; falling back to %s",
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS

    if value < MIN_TIMEOUT_SECONDS or value > MAX_TIMEOUT_SECONDS:
        logger.warning(
            "COMMON_CRAWL_TIMEOUT_SECONDS=%s is outside the allowed range [%s, %s]; falling back to %s",
            value,
            MIN_TIMEOUT_SECONDS,
            MAX_TIMEOUT_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS

    return value


def _resolve_user_agent() -> str:
    raw = os.environ.get("COMMON_CRAWL_USER_AGENT", "").strip()
    if not raw:
        return DEFAULT_USER_AGENT

    if len(raw) > MAX_USER_AGENT_LENGTH:
        logger.warning(
            "COMMON_CRAWL_USER_AGENT is %d characters, exceeding the %d-character cap; falling back to %r",
            len(raw),
            MAX_USER_AGENT_LENGTH,
            DEFAULT_USER_AGENT,
        )
        return DEFAULT_USER_AGENT

    return raw


def _resolve_index_budget_seconds() -> float:
    raw = os.environ.get(
        "COMMON_CRAWL_INDEX_BUDGET_SECONDS", str(DEFAULT_INDEX_BUDGET_SECONDS)
    ).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "COMMON_CRAWL_INDEX_BUDGET_SECONDS=%r is not a number; falling back to %s",
            raw,
            DEFAULT_INDEX_BUDGET_SECONDS,
        )
        return DEFAULT_INDEX_BUDGET_SECONDS

    if value < MIN_INDEX_BUDGET_SECONDS or value > MAX_INDEX_BUDGET_SECONDS:
        logger.warning(
            "COMMON_CRAWL_INDEX_BUDGET_SECONDS=%s is outside the allowed range [%s, %s]; falling back to %s",
            value,
            MIN_INDEX_BUDGET_SECONDS,
            MAX_INDEX_BUDGET_SECONDS,
            DEFAULT_INDEX_BUDGET_SECONDS,
        )
        return DEFAULT_INDEX_BUDGET_SECONDS

    return value


def load_common_crawl_settings() -> CommonCrawlSettings:
    """Reads COMMON_CRAWL_* env vars fresh on every call (mirrors the
    AI_OVERVIEW_PROVIDER_MODE/CHATGPT_* pattern elsewhere in this
    codebase), so a test or an operator changing the environment takes
    effect on the next request without a restart being required by
    this function itself.
    """
    return CommonCrawlSettings(
        enabled=_resolve_enabled(),
        index=_resolve_index(),
        max_results=_resolve_max_results(),
        timeout_seconds=_resolve_timeout_seconds(),
        user_agent=_resolve_user_agent(),
        index_budget_seconds=_resolve_index_budget_seconds(),
    )
