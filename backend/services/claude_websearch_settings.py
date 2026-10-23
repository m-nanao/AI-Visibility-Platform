"""Task 6-D-4A-2 (feature/claude-websearch-supplement): environment
variables for Claude's *conditional* Web-search supplement.

Deliberately its own module — not added to services/claude_settings.py
or services/claude_provider.py — so the existing no-search Claude
observation's own settings/gating code is left completely untouched by
this task (mirrors services/chatgpt_websearch_settings.py's identical
reasoning for the same requirement on the ChatGPT side).

**Why this module also carries its own model/max-output-tokens
settings, unlike chatgpt_websearch_settings.py (which is just the one
boolean flag and reuses services/chatgpt_settings.py's model/token
settings as-is).** Task 6-D-4A-1's investigation found that
services/claude_settings.py's DEFAULT_MODEL ("claude-sonnet-4-5",
i.e. the dateless alias for `claude-sonnet-4-5-20250929`) was marked
"Deprecated" by Anthropic on 2026-09-30 with a tentative retirement
date of 2026-11-30 — see
https://platform.claude.com/docs/en/about-claude/model-deprecations
(fetched 2026-10-23). Reusing that same default for a brand-new
feature would mean shipping it already pointed at a model Anthropic
is actively retiring. Per this task's own instruction ("検索補完用モ
デルが既存モデルと異なる場合、結果メタデータに使用モデルを識別可能な
形で記録する"), this module's own default is therefore
`claude-sonnet-5-5` — Anthropic's documented recommended replacement
for claude-sonnet-4-5 on that same page — kept entirely independent of
CLAUDE_MODEL so services/claude_settings.py/claude_provider.py/
claude_client.py (the existing no-search observation) are never
touched or implicitly affected by this choice.

**Known limitation, disclosed rather than silently assumed**: this
codebase has no way to call Anthropic's Models API (GET
/v1/models/{model}, capabilities.server_tools.web_search.supported)
without making a real, billable-adjacent authenticated request, which
this task's own constraints forbid. Whether `claude-sonnet-5-5`
actually accepts the web_search tool could not be verified against a
live API in this task — only against Anthropic's web-search-tool/
tool-reference documentation, which describes the capability check but
does not enumerate a per-model support matrix. This is exactly the
"モデル対応を実APIで確認できない場合は、その制約を明記してmockによる
実装検証を進める" case this task's own instructions anticipated — see
this task's completion report for the full caveat. Nothing in this
module or anything that calls it ever makes a real Anthropic API call
on its own; CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED defaults to False
specifically so this limitation can be resolved (via the Models API or
a real sandbox call) before the feature is ever turned on for real.

Default is always off, and this module never enables anything by
itself — mirrors services/chatgpt_websearch_settings.py's identical
guarantee.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Default OFF, as required. This flag alone only ever *permits* the
# websearch supplement to be attempted — it is never sufficient on its
# own: services/claude_websearch_provider.py's
# attempt_claude_websearch_supplement() additionally requires quota
# enforcement to be enabled, CLAUDE_API_KEY to be configured, an
# eligible recognitionLevel, and a successful quota reservation before
# ever calling the Anthropic API. Never read anywhere in the existing
# no-search Claude observation path (services/claude_client.py/
# claude_provider.py).
DEFAULT_CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED = False

# See module docstring for why this is independent of
# services/claude_settings.py's DEFAULT_MODEL.
DEFAULT_CLAUDE_WEBSEARCH_MODEL = "claude-sonnet-5-5"

# Task 6-D-4A-2 item 3: a websearch-supplement answer tends to need
# more room than the no-search observation's own default (700, see
# services/claude_settings.py's DEFAULT_MAX_OUTPUT_TOKENS) — the
# model's own tool-use content (the search query, the search-result
# block) and the cited synthesis afterward both have to fit in the
# same budget, mirroring exactly why
# services/chatgpt_websearch_client.py's own
# MIN_MAX_OUTPUT_TOKENS_FLOOR exists for the OpenAI side. 2000 is this
# task's own starting candidate (per its own instruction) — deliberately
# modest, not the model's 128K ceiling, since this card's prompt asks
# for a short company-overview answer only (see
# services/claude_websearch_client.py's SYSTEM_PROMPT/
# build_claude_websearch_user_prompt()) and an unnecessarily high
# output cap only raises worst-case token cost for no real benefit.
DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS = 2000
MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS = 100
# Generous headroom over the 2000 default without approaching anything
# close to the model's real ceiling (128K, per
# https://platform.claude.com/docs/en/models/sonnet-5-5/overview) —
# keeps a misconfigured, too-large value from silently becoming an
# expensive request (Task 6-D-4A-2 item 3: "不必要に高額な出力設定は
# 採用しない").
MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS = 4000


def is_claude_websearch_supplement_enabled() -> bool:
    """Reads CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED fresh on every call
    (mirrors every other env-reading function in this codebase — no
    caching, so a test can monkeypatch os.environ and simply call this
    again). Unrecognized values fall back to the safe default (False),
    logged as a warning rather than silently promoted to "enabled".
    """
    raw = os.environ.get("CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED")
    if raw is None:
        return DEFAULT_CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED=%r is not a recognized boolean; "
        "falling back to %s",
        raw,
        DEFAULT_CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED,
    )
    return DEFAULT_CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED


def get_claude_websearch_model() -> str:
    """Reads CLAUDE_WEBSEARCH_MODEL, falling back to
    DEFAULT_CLAUDE_WEBSEARCH_MODEL — see module docstring for why this
    is independent of CLAUDE_MODEL/services.claude_settings.DEFAULT_MODEL.
    """
    raw = os.environ.get("CLAUDE_WEBSEARCH_MODEL", "").strip()
    return raw or DEFAULT_CLAUDE_WEBSEARCH_MODEL


def get_claude_websearch_max_output_tokens() -> int:
    """Reads CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS, clamped to
    [MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
    MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS] — mirrors
    services/claude_settings.py's own
    _resolve_max_output_tokens()/MIN_MAX_OUTPUT_TOKENS/
    MAX_MAX_OUTPUT_TOKENS validation style (an out-of-range or
    unparseable value is logged as a warning and replaced with this
    module's own default, never silently clamped to the nearer bound).
    """
    raw = os.environ.get(
        "CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS", str(DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS)
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS

    if value < MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS or value > MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS:
        logger.warning(
            "CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS=%d is outside the allowed range [%d, %d]; "
            "falling back to %d",
            value,
            MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
            MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
            DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS

    return value
