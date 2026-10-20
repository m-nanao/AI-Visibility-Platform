"""Shared system/user prompt and summarization logic for all three
single-call AI brand-observation providers (services/chatgpt_client.py,
services/claude_client.py, services/gemini_client.py) — kept in one
place so all three ask the exact same question about a brand and can
be meaningfully compared side-by-side (Task 6-C Review Prep 1,
feature/unify-ai-observation-prompts).

Historically, Claude/Gemini shared this module while ChatGPT kept its
own, differently-worded prompt (predating this module) — see
docs/36_multi_ai_comparison_design.md for that original design. Task
6-C Review Prep 1 unified all three onto this single definition so a
依頼者 comparing the three answers is comparing responses to the
*same* question, not three subtly different ones. All three
observation providers still share the same underlying caveat (a
single non-browsing text-generation call, not a representation of the
AI service's full behavior).
"""

SYSTEM_PROMPT = (
    "あなたは、AIがブランドをどのように説明するかを観測するための評価用アシスタントです。"
    "Web検索は行わず、一般的な知識に基づいて日本語で回答してください。"
    "不確かな点は断定しすぎず、簡潔に述べてください。"
)


def build_user_prompt(brand_name: str) -> str:
    """The same question asked of every single-call AI brand-observation
    provider (ChatGPT, Claude, Gemini), so their answers can be
    compared on identical observation points for the same brand (Task
    6-C Review Prep 1). Deliberately a neutral "how is this brand
    generally perceived" question — no comparison-shopping/competitor
    framing (that wording was removed in this task per the project's
    confirmed policy of not adding search-demand-research framing such
    as "おすすめ"/"選び方").
    """
    return (
        "次のブランドについて、一般的にどのような企業・サービスとして認識されるかを"
        "日本語で説明してください。\n"
        "\n"
        f"ブランド名：{brand_name}\n"
        "\n"
        "以下の観点について回答してください。\n"
        "\n"
        "1. どのような企業・ブランド・サービスとして認識されるか\n"
        "2. 主な事業・提供サービス\n"
        "3. 想定される利用者や用途\n"
        "4. 代表的な特徴・強み\n"
        "5. 不明な点や認識が曖昧な点\n"
        "\n"
        "Web検索は行わず、モデルが持つ知識に基づいて回答してください。\n"
        "確信できない情報は推測で補わず、不明であることを明示してください。"
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
