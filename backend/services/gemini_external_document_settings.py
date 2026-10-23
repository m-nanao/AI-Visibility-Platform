"""Task 6-D-4C-2 (feature/gemini-external-document-supplement):
environment variables for Gemini's *conditional* external-document
supplement — Gemini answering from Web documents this application
itself fetched (services/web_fetcher.py), with no Google Search
grounding tool involved at all.

Deliberately its own module — not added to services/gemini_settings.py
or services/gemini_provider.py, and not added to
services/gemini_websearch_settings.py either — so the existing
no-search Gemini observation's own settings/gating code, and the
(still-disabled, ToS-pending) Google-Search-grounding supplement's own
settings, are both left completely untouched by this task.

**Model allowlist, mirroring services/gemini_websearch_settings.py's
own design** — Task 6-D-4C-2's own requirement: "モデル設定を環境変数で
上書きする場合は、今回の許可モデル以外をAPI呼び出し前に拒否する". Unlike
the Google-Search-grounding supplement (where the allowlist exists
because of Gemini 3+'s unbounded per-query billing), this feature has
no comparable per-call cost-explosion risk (it never offers any
server-side tool at all — the cost is a single, ordinary
`generateContent` call, same shape as the no-search observation's own
call) — the allowlist here exists simply to keep this task's initial
scope narrow and auditable, not because of a specific billing hazard
like the grounding supplement's. `gemini-2.5-flash` is the only model
this task was asked to support.

Default is always off, and this module never enables anything by
itself.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED = False

GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS = frozenset({"gemini-2.5-flash"})

DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MODEL = "gemini-2.5-flash"

# Task 6-D-4C-2 item 4 — mirrors
# services/gemini_websearch_settings.py's own reasoning: this
# supplement's answer needs a bit more room than the no-search
# observation's own default (700, see services/gemini_settings.py's
# DEFAULT_MAX_OUTPUT_TOKENS) to synthesize across up to three input
# documents. Deliberately modest, not the model's real ceiling.
DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS = 2000
MIN_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS = 100
MAX_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS = 4000

# Task 6-D-4C-2 item 3's own initial values — see
# services/gemini_external_document_client.py's own docstring for how
# these are applied (at most this many documents, each capped at this
# many characters, the combined total capped at the third value).
# Deliberately plain module constants, not environment-configurable —
# this task's own instruction gives these as fixed initial values, not
# operator-tunable settings; making them env-configurable is left to a
# future task if real usage shows a need.
MAX_INPUT_DOCUMENTS = 3
MAX_CHARS_PER_DOCUMENT = 5000
MAX_TOTAL_INPUT_CHARS = 10000


def is_gemini_external_document_supplement_enabled() -> bool:
    """Reads GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED fresh on every
    call — no caching, so a test can monkeypatch os.environ and simply
    call this again. Unrecognized values fall back to the safe default
    (False), logged as a warning rather than silently promoted to
    "enabled"."""
    raw = os.environ.get("GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED")
    if raw is None:
        return DEFAULT_GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED=%r is not a recognized boolean; "
        "falling back to %s",
        raw,
        DEFAULT_GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED,
    )
    return DEFAULT_GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED


def get_gemini_external_document_model() -> str:
    """Reads GEMINI_EXTERNAL_DOCUMENT_MODEL, falling back to
    DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MODEL. **This function does not
    itself enforce the allowlist** — see
    services/gemini_external_document_provider.py for where the
    resolved value is checked against
    GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS and rejected before any API
    call if it isn't on it.
    """
    raw = os.environ.get("GEMINI_EXTERNAL_DOCUMENT_MODEL", "").strip()
    return raw or DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MODEL


def get_gemini_external_document_max_output_tokens() -> int:
    """Reads GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS, clamped to
    [MIN_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS,
    MAX_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS]."""
    raw = os.environ.get(
        "GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS",
        str(DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS

    if (
        value < MIN_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS
        or value > MAX_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS
    ):
        logger.warning(
            "GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS=%d is outside the allowed range "
            "[%d, %d]; falling back to %d",
            value,
            MIN_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS,
            MAX_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS,
            DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_GEMINI_EXTERNAL_DOCUMENT_MAX_OUTPUT_TOKENS

    return value
