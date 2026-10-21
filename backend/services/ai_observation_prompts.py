"""Shared system/user prompt, recognition-level classification, and
summarization logic for all three single-call AI brand-observation
providers (services/chatgpt_client.py, services/claude_client.py,
services/gemini_client.py) — kept in one place so all three ask the
exact same question about a brand and can be meaningfully compared
side-by-side (Task 6-C Review Prep 1, feature/unify-ai-observation-prompts).

Historically, Claude/Gemini shared this module while ChatGPT kept its
own, differently-worded prompt (predating this module) — see
docs/36_multi_ai_comparison_design.md for that original design. Task
6-C Review Prep 1 unified all three onto this single definition so a
依頼者 comparing the three answers is comparing responses to the
*same* question, not three subtly different ones. All three
observation providers still share the same underlying caveat (a
single non-browsing text-generation call, not a representation of the
AI service's full behavior).

Task 6-D-1 (feature/recognition-level-classification) adds
`classify_recognition_level()` and `PROMPT_VERSION`: the prompt now
asks the model to self-report how specifically it recognizes the
brand (rather than silently guessing from the name alone), and this
module parses that self-report into one of models.RecognitionLevel's
five values. **This classification is the model's own self-report,
never independently verified against any Web source** — see
classify_recognition_level()'s own docstring for the full caveat. No
Web search is added by this task; that remains a future, separate
task that can read this field once it exists.
"""

from models import RecognitionLevel

# Bumped whenever build_user_prompt()'s wording changes meaningfully
# enough that a saved recognitionLevel/summary from an older version
# shouldn't be assumed comparable to a newer one. Stored alongside the
# observation (see models.ChatGptProviderInfo.promptVersion and
# siblings) purely for future diagnostics/analysis — nothing in this
# codebase currently branches on its value.
PROMPT_VERSION = "no_search_v1"

SYSTEM_PROMPT = (
    "あなたは、AIがブランドをどのように説明するかを観測するための評価用アシスタントです。"
    "Web検索は行わず、一般的な知識に基づいて日本語で回答してください。"
    "不確かな点は断定しすぎず、簡潔に述べてください。"
)

# The exact label text the model is asked to echo back — matched
# verbatim (see _RECOGNITION_LABELS below) rather than inferred from
# the surrounding prose, so classification doesn't depend on fuzzy
# text matching of the free-form answer itself (Task 6-D-1 "9.
# 既存のmentionedフラグを認識精度の証明として使わない" — this label is a
# completely separate signal from the old substring-based `mentioned`
# check, which only ever detected whether the brand name string
# appeared anywhere in the text, including inside a "分かりません"-style
# non-recognition answer that simply echoes the name back).
_RECOGNITION_LABEL_LINE_PREFIX = "認識レベル"
_RECOGNITION_LABELS: dict[str, RecognitionLevel] = {
    "具体的な認識あり": "specific_knowledge",
    "部分的な認識": "partial_knowledge",
    "対象企業を識別できない": "unidentified",
    "名称からの推測のみ": "name_inference_only",
    "判定不能": "indeterminate",
}


def build_user_prompt(brand_name: str) -> str:
    """The same question asked of every single-call AI brand-observation
    provider (ChatGPT, Claude, Gemini), so their answers can be
    compared on identical observation points for the same brand (Task
    6-C Review Prep 1). Deliberately a neutral, identification-first
    question (Task 6-D-1): asks the model to say what it actually
    knows about the specifically-identified brand, explicitly forbids
    guessing a business/industry purely from how the name sounds, and
    asks for an explicit self-reported recognition-level label in a
    fixed, parseable format (see classify_recognition_level() below)
    — no comparison-shopping/competitor framing either (removed in
    Task 6-C Review Prep 1 per the project's confirmed policy against
    search-demand-research framing such as "おすすめ"/"選び方").
    """
    return (
        f"「{brand_name}」という企業・ブランドについて、あなたが把握している情報を"
        "教えてください。\n"
        "\n"
        "対象を具体的に識別できる場合は、知っている範囲で企業概要・主な事業・特徴を"
        "説明してください。\n"
        "対象を識別できない場合は、その旨を明示してください。\n"
        "名称の印象だけから事業内容や特徴を推測しないでください。\n"
        "不確かな情報は断定せず、不明な場合は不明としてください。\n"
        "Web検索や外部情報の取得は行わず、現在のモデルの知識に基づいて回答して"
        "ください。\n"
        "\n"
        "回答の最後に、他の文章を含めず次の1行だけを必ず追加してください。\n"
        f"{_RECOGNITION_LABEL_LINE_PREFIX}："
        "[具体的な認識あり/部分的な認識/対象企業を識別できない/名称からの推測のみ/判定不能]"
    )


def classify_recognition_level(text: str) -> RecognitionLevel:
    """Parses the model's self-reported recognition-level label (the
    fixed last line build_user_prompt() asks for) out of its raw
    answer text.

    **This is a provisional, model-self-reported observation, never a
    verified fact.** A model can say "具体的な認識あり" (specific
    knowledge) and still be describing the wrong company entirely, or
    say "判定不能" while actually having useful information it failed
    to format correctly — this function only ever reports *what the
    model claimed about itself*, exactly as unreliable as any other
    single, non-browsing text-generation answer. Task 6-D-1's "5"/"6"
    requirements: this classification must never be treated as proof
    of "accurate recognition", and "answered with specific-sounding
    detail" must stay a separate concept from "the detail is factually
    correct" — neither this function nor anything calling it attempts
    the latter; that is explicitly deferred to a future Web-comparison
    task that can read this field once it exists.

    Falls back to `"indeterminate"` (never silently to a
    recognized-looking value) whenever the expected label line is
    missing, malformed, or names something outside
    `_RECOGNITION_LABELS` — Task 6-D-1 "7. 回答の解析が失敗した場合は
    indeterminateとし、認識ありとみなさない". Matching is deliberately
    tolerant of minor formatting drift a model might introduce (a
    half-width colon, extra whitespace, or wrapping the label in
    brackets) without falling back to substring/fuzzy matching against
    the free-form prose above the label line.
    """
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if _RECOGNITION_LABEL_LINE_PREFIX not in line:
            continue
        # Only ever consider text after the prefix on this one line —
        # never the rest of the answer, which stays free-form prose
        # this function makes no attempt to interpret.
        _, _, after_prefix = line.partition(_RECOGNITION_LABEL_LINE_PREFIX)
        candidate = after_prefix.strip(" :：[]　")
        return _RECOGNITION_LABELS.get(candidate, "indeterminate")
    return "indeterminate"


_SUMMARY_MAX_CHARS = 200
# fullSummary is a detail view, not an excerpt — matches
# services/chatgpt_client.py's/services/dataforseo_client.py's own
# fullSummary sizing.
_FULL_SUMMARY_MAX_CHARS = 2500


def strip_recognition_label_line(text: str) -> str:
    """Removes the trailing "認識レベル：..." self-report line
    build_user_prompt() asks for, so the human-readable summary/
    fullSummary shown in the UI (Task 6-D-1 "3. 人間が読める回答本文を
    維持する") stays the model's actual prose answer, never the
    technical label line verbatim. Classification itself
    (classify_recognition_level()) always runs on the *original*,
    unstripped text — this function is only ever applied afterward,
    purely for display. A no-op (returns `text` unchanged) if the
    label line is missing or unparseable, so a model that didn't
    follow the format still gets its full prose shown as-is.
    """
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            continue
        if _RECOGNITION_LABEL_LINE_PREFIX in line:
            return "\n".join(lines[:index]).rstrip()
        break
    return text


def summarize_observation_text(text: str, brand_name: str) -> tuple[bool, str, str]:
    """Reduces a model's raw answer text to (mentioned, summary,
    full_summary) — identical logic to services/chatgpt_client.py's
    private `_summarize()`, duplicated here rather than imported so
    this module has no dependency on chatgpt_client.py (keeping the two
    provider families independent, per module docstring above).
    `summary` is a short excerpt (<= _SUMMARY_MAX_CHARS); `full_summary`
    is the fuller text (<= _FULL_SUMMARY_MAX_CHARS). Both are computed
    from the recognition-label line already stripped out (Task 6-D-1)
    — `mentioned` is still computed from the *original* `text`,
    unaffected either way since the label line never contains the
    brand name.
    """
    mentioned = brand_name.lower() in text.lower()
    text = strip_recognition_label_line(text)

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
