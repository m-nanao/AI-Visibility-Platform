"""Task 6-D-4B-2 (feature/gemini-websearch-supplement): environment
variables for Gemini's *conditional* Google Search grounding
supplement.

Deliberately its own module — not added to services/gemini_settings.py
or services/gemini_provider.py — so the existing no-search Gemini
observation's own settings/gating code is left completely untouched
by this task (mirrors services/chatgpt_websearch_settings.py's and
services/claude_websearch_settings.py's identical reasoning for the
same requirement).

**Why this feature allows only one specific model, unlike the ChatGPT/
Claude websearch supplements (which accept any configured model
string).** Task 6-D-4B-1's investigation
(https://ai.google.dev/gemini-api/docs/generate-content/google-search,
fetched 2026-10-24) found that Gemini's grounding billing differs
fundamentally by model generation: Gemini 2.5 and earlier are billed
per *prompt* (one API call = one billing unit, regardless of how many
search queries the model issues internally), while Gemini 3 and later
are billed per *executed search query*, with no API parameter found to
cap how many queries a single call may issue. Unlike OpenAI's
`max_tool_calls`/Anthropic's `max_uses`, there is no per-request search
count ceiling on the Gemini side at all. Because this task's own cost
safety design (one `google_websearch` quota reservation == one bounded
API call) depends on a *known, fixed* cost per call, only
`gemini-2.5-flash` (per-prompt billing, and the model already used for
the no-search observation — see services/gemini_settings.py's own
DEFAULT_MODEL) is permitted. `GEMINI_WEBSEARCH_ALLOWED_MODELS` is a
closed allowlist, not a cap or a default suggestion — see
services/gemini_websearch_provider.py's own model-gate, which rejects
any other configured value *before* ever reserving quota or calling
the API, rather than silently falling back to the allowed model.

Default is always off, and this module never enables anything by
itself — mirrors the ChatGPT/Claude websearch settings modules'
identical guarantee.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Default OFF, as required. This flag alone only ever *permits* the
# websearch supplement to be attempted — it is never sufficient on its
# own: services/gemini_websearch_provider.py's
# attempt_gemini_websearch_supplement() additionally requires quota
# enforcement to be enabled, GEMINI_API_KEY to be configured, an
# eligible recognitionLevel, the configured model to be on the
# allowlist, and a successful quota reservation before ever calling
# the Gemini API. Never read anywhere in the existing no-search Gemini
# observation path (services/gemini_client.py/gemini_provider.py).
DEFAULT_GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED = False

# See module docstring — the only model this feature will ever call,
# regardless of what GEMINI_WEBSEARCH_MODEL is set to. A closed set
# (not just a default), enforced by
# services/gemini_websearch_provider.py's own gate.
GEMINI_WEBSEARCH_ALLOWED_MODELS = frozenset({"gemini-2.5-flash"})

DEFAULT_GEMINI_WEBSEARCH_MODEL = "gemini-2.5-flash"

# Task 6-D-4B-2 item 3 — mirrors
# services/claude_websearch_settings.py's own reasoning: a websearch-
# supplement answer needs more room than the no-search observation's
# own default (700, see services/gemini_settings.py's
# DEFAULT_MAX_OUTPUT_TOKENS) for the grounding/citation content plus
# the cited synthesis. Deliberately modest (not the model's real
# ceiling), since the prompt asks only for a short company-overview
# answer (see services/gemini_websearch_client.py's SYSTEM_PROMPT).
DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS = 2000
MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS = 100
MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS = 4000


def is_gemini_websearch_supplement_enabled() -> bool:
    """Reads GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED fresh on every call —
    no caching, so a test can monkeypatch os.environ and simply call
    this again. Unrecognized values fall back to the safe default
    (False), logged as a warning rather than silently promoted to
    "enabled"."""
    raw = os.environ.get("GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED")
    if raw is None:
        return DEFAULT_GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED=%r is not a recognized boolean; "
        "falling back to %s",
        raw,
        DEFAULT_GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED,
    )
    return DEFAULT_GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED


def get_gemini_websearch_model() -> str:
    """Reads GEMINI_WEBSEARCH_MODEL, falling back to
    DEFAULT_GEMINI_WEBSEARCH_MODEL. **This function does not itself
    enforce the allowlist** — it only resolves what was configured, so
    a misconfigured value is still visible/loggable; see
    services/gemini_websearch_provider.py for where that value is
    checked against GEMINI_WEBSEARCH_ALLOWED_MODELS and rejected
    before any API call if it isn't on it.
    """
    raw = os.environ.get("GEMINI_WEBSEARCH_MODEL", "").strip()
    return raw or DEFAULT_GEMINI_WEBSEARCH_MODEL


def get_gemini_websearch_max_output_tokens() -> int:
    """Reads GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS, clamped to
    [MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
    MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS] — mirrors
    services/gemini_settings.py's own validation style (an
    out-of-range or unparseable value is logged as a warning and
    replaced with this module's own default, never silently clamped
    to the nearer bound)."""
    raw = os.environ.get(
        "GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS", str(DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS)
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS

    if (
        value < MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS
        or value > MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS
    ):
        logger.warning(
            "GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS=%d is outside the allowed range [%d, %d]; "
            "falling back to %d",
            value,
            MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
            MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
            DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS

    return value
