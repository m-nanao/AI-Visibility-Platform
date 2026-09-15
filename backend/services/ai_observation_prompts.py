"""Shared system/user prompt and summarization logic for the Claude and
Gemini observation providers (services/claude_client.py,
services/gemini_client.py) — kept in one place so both ask the exact
same question about a brand and can be meaningfully compared
side-by-side, per docs/36_multi_ai_comparison_design.md.

Deliberately not shared with services/chatgpt_client.py: that module's
existing prompt predates this one and is already in production
(feature/chatgpt-observation-provider) — changing it now would be a
behavioral change to an existing, already-verified feature, which is
out of scope for adding the Claude/Gemini foundation. Claude and
Gemini instead use this newer, explicitly comparison-oriented prompt;
all three observation providers still share the same underlying
caveat (a single non-browsing text-generation call, not a
representation of the AI service's full behavior).
"""

SYSTEM_PROMPT = (
    "あなたは、AIがブランドをどのように説明するかを観測するための評価用アシスタントです。"
    "Web検索は行わず、一般的な知識に基づいて日本語で回答してください。"
    "不確かな点は断定しすぎず、簡潔に述べてください。"
)


def build_user_prompt(brand_name: str) -> str:
    """The same question asked of every multi-AI observation provider
    (Claude, Gemini), so their answers can be compared on identical
    observation points for the same brand — see
    docs/36_multi_ai_comparison_design.md "3.2 比較観点".
    """
    return (
        f"対象ブランド「{brand_name}」について、Web検索ユーザーが比較検討する場面を想定し、"
        "以下を日本語で簡潔に回答してください。\n"
        "\n"
        "- どのようなブランド/サービスとして説明されるか\n"
        "- どのカテゴリ・用途で言及されやすいか\n"
        "- 強みとして説明されそうな点\n"
        "- 注意点や不足しそうな情報\n"
        "- 競合や比較対象がある場合の文脈\n"
        "\n"
        "この回答は観測用です。事実確認済みレポートではなく、モデル回答傾向の確認として扱います。"
    )


_SUMMARY_MAX_CHARS = 200
# fullSummary is a detail view, not an excerpt — matches
# services/chatgpt_client.py's/services/dataforseo_client.py's own
# fullSummary sizing.
_FULL_SUMMARY_MAX_CHARS = 2500


def summarize_observation_text(text: str, brand_name: str) -> tuple[bool, str, str]:
    """Reduces a model's raw answer text to (mentioned, summary,
    full_summary) — identical logic to services/chatgpt_client.py's
    private `_summarize()`, duplicated here rather than imported so
    this module has no dependency on chatgpt_client.py (keeping the two
    provider families independent, per module docstring above).
    `summary` is a short excerpt (<= _SUMMARY_MAX_CHARS); `full_summary`
    is the fuller text (<= _FULL_SUMMARY_MAX_CHARS).
    """
    mentioned = brand_name.lower() in text.lower()

    cleaned = " ".join(text.split())
    if len(cleaned) > _SUMMARY_MAX_CHARS:
        summary = cleaned[:_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        summary = cleaned

    if len(text) > _FULL_SUMMARY_MAX_CHARS:
        full_summary = text[:_FULL_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        full_summary = text

    return mentioned, summary, full_summary
