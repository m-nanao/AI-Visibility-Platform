"""Task 6-D-3 (feature/chatgpt-websearch-supplement): the one new
Backend environment variable this task adds.

Deliberately its own tiny module — not added to
services/chatgpt_settings.py or services/chatgpt_provider.py — so the
existing no-search ChatGPT observation's own settings/gating code is
left completely untouched by this task (per that task's own
requirement: "検索なしの既存OpenAI観測を変更しない"). Mirrors the
boolean-flag-reading style of services/analyze_quota_settings.py's
`_resolve_bool_env()` rather than importing that private helper across
modules.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Default OFF, as required. This flag alone only ever *permits* the
# websearch supplement to be attempted — it is never sufficient on its
# own: services/chatgpt_websearch_provider.py's
# attempt_chatgpt_websearch_supplement() additionally requires quota
# enforcement to be enabled, OPENAI_API_KEY to be configured, an
# eligible recognitionLevel, and a successful quota reservation before
# ever calling the OpenAI API. Never read anywhere in the existing
# no-search ChatGPT observation path
# (services/chatgpt_client.py/chatgpt_provider.py).
DEFAULT_CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED = False


def is_chatgpt_websearch_supplement_enabled() -> bool:
    """Reads CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED fresh on every call
    (mirrors every other env-reading function in this codebase — no
    caching, so a test can monkeypatch os.environ and simply call this
    again). Unrecognized values fall back to the safe default (False),
    logged as a warning rather than silently promoted to "enabled".
    """
    raw = os.environ.get("CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED")
    if raw is None:
        return DEFAULT_CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED=%r is not a recognized boolean; "
        "falling back to %s",
        raw,
        DEFAULT_CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED,
    )
    return DEFAULT_CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED
