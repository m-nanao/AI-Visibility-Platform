"""Task 6-D-5C-2 (feature/claude-fact-extraction-mvp): environment
variables for the Claude-based fact-extraction MVP (decomposing one
ChatGPT no-search AI answer into per-claim factual assertions — see
services/fact_extraction_provider.py's module docstring for the full
gating/attempt flow).

Deliberately its own module — not added to services/claude_settings.py
or services/claude_websearch_settings.py — so neither the existing
no-search Claude observation's settings nor the (also independent)
Claude Web-search-supplement settings are touched by this task. Reuses
services/claude_settings.py's get_claude_credentials() as-is (same
CLAUDE_API_KEY — this is still the same Anthropic account, just a
different call/model/token-budget configuration), but every other
setting here (model, max output tokens) is its own, independent of
CLAUDE_MODEL/CLAUDE_WEBSEARCH_MODEL.

**Model allowlist, mirroring services/gemini_external_document_settings.py's
design**: Task 6-D-5C-2's own requirement ("モデルIDは許可リストで検証")
— `claude-sonnet-5-5` (the same non-deprecated model
services/claude_websearch_settings.py already settled on for a new
Claude-calling feature in this codebase, see that module's own
docstring for the full claude-sonnet-4-5-deprecation reasoning) is the
only model this task was asked to support.

Default is always off (`FACT_EXTRACTION_ENABLED=false`), and this
module never enables anything by itself.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_FACT_EXTRACTION_ENABLED = False

FACT_EXTRACTION_ALLOWED_MODELS = frozenset({"claude-sonnet-5-5"})

DEFAULT_FACT_EXTRACTION_MODEL = "claude-sonnet-5-5"

# A structured-extraction answer (up to MAX_FACT_CLAIMS_PER_CARD items,
# models.py's own cap of 30, each with a category/nature/state/claim
# text/source quote) needs more room than a short observation summary
# — deliberately modest relative to the model's real ceiling, not an
# attempt to use its maximum. See
# services/fact_extraction_client.py's own docstring for how the
# system prompt bounds the realistic output size further.
DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS = 4000
MIN_FACT_EXTRACTION_MAX_OUTPUT_TOKENS = 500
MAX_FACT_EXTRACTION_MAX_OUTPUT_TOKENS = 8000

# Task 6-D-5C-2 item 3: "1runにつき最大1 APIリクエスト" / "自動リトライ
# 禁止" / "自動継続禁止" — deliberately a plain module constant, never
# environment-configurable, so no misconfiguration can ever raise it.
# Enforced structurally by services/fact_extraction_provider.py (it
# only ever calls the Claude client once per attempt, with no retry
# loop anywhere in this subsystem), not by this constant alone — this
# constant exists only to give that invariant one documented, testable
# name.
MAX_API_REQUESTS_PER_ANALYSIS_RUN = 1

# HTTP timeout for the single extraction call. Task 6-D-5C-2A final
# review item 1: unlike services/ai_gap_comparison.py's own 30s (a
# manual, on-demand endpoint with no competing time budget), this call
# happens *inside* /analyze's own request — both the authenticated
# sync path (bounded by app/api/analyze/route.ts's
# PYTHON_API_TIMEOUT_MS, 55s, shared with the no-search ChatGPT/Claude/
# Gemini observations and any already-enabled websearch/external-
# document supplement ahead of it in the same request) and the async
# job worker path (bounded by its own, much larger lease —
# services/analysis_jobs_settings.py's DEFAULT_LEASE_SECONDS=180,
# extendable by its heartbeat — so this constant is sized for the
# *sync* path's tighter budget, not the async path's, which has ample
# headroom regardless). 20s (not 30s) matches
# services/chatgpt_client.py's/claude_client.py's/gemini_client.py's
# own no-search REQUEST_TIMEOUT_SECONDS ceiling — deliberately more
# conservative than the already-shipped Web-search supplements' 45s,
# since this call is additive on top of whichever of those happen to
# also be enabled for the same request, not a replacement for them.
# See services/fact_extraction_provider.py's module docstring for the
# full timing analysis and why the sync path is still kept (not async-
# only) despite this shared-budget risk.
REQUEST_TIMEOUT_SECONDS = 20.0


def is_fact_extraction_enabled() -> bool:
    """Reads FACT_EXTRACTION_ENABLED fresh on every call — no caching,
    so a test can monkeypatch os.environ and simply call this again.
    Unrecognized values fall back to the safe default (False), logged
    as a warning rather than silently promoted to "enabled"."""
    raw = os.environ.get("FACT_EXTRACTION_ENABLED")
    if raw is None:
        return DEFAULT_FACT_EXTRACTION_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "FACT_EXTRACTION_ENABLED=%r is not a recognized boolean; falling back to %s",
        raw,
        DEFAULT_FACT_EXTRACTION_ENABLED,
    )
    return DEFAULT_FACT_EXTRACTION_ENABLED


def get_fact_extraction_model() -> str:
    """Reads FACT_EXTRACTION_MODEL, falling back to
    DEFAULT_FACT_EXTRACTION_MODEL. **This function does not itself
    enforce the allowlist** — see services/fact_extraction_provider.py
    for where the resolved value is checked against
    FACT_EXTRACTION_ALLOWED_MODELS and rejected before any API call if
    it isn't on it.
    """
    raw = os.environ.get("FACT_EXTRACTION_MODEL", "").strip()
    return raw or DEFAULT_FACT_EXTRACTION_MODEL


def get_fact_extraction_max_output_tokens() -> int:
    """Reads FACT_EXTRACTION_MAX_OUTPUT_TOKENS, clamped to
    [MIN_FACT_EXTRACTION_MAX_OUTPUT_TOKENS,
    MAX_FACT_EXTRACTION_MAX_OUTPUT_TOKENS]."""
    raw = os.environ.get(
        "FACT_EXTRACTION_MAX_OUTPUT_TOKENS", str(DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS)
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "FACT_EXTRACTION_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS

    if (
        value < MIN_FACT_EXTRACTION_MAX_OUTPUT_TOKENS
        or value > MAX_FACT_EXTRACTION_MAX_OUTPUT_TOKENS
    ):
        logger.warning(
            "FACT_EXTRACTION_MAX_OUTPUT_TOKENS=%d is outside the allowed range [%d, %d]; "
            "falling back to %d",
            value,
            MIN_FACT_EXTRACTION_MAX_OUTPUT_TOKENS,
            MAX_FACT_EXTRACTION_MAX_OUTPUT_TOKENS,
            DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS

    return value
