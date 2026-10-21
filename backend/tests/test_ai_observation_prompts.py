"""Tests for services/ai_observation_prompts.py's build_user_prompt()
— the single shared user-prompt generator ChatGPT/Claude/Gemini all
call as of Task 6-C Review Prep 1 (feature/unify-ai-observation-prompts)
— plus Task 6-D-1's classify_recognition_level()/
strip_recognition_label_line() (feature/recognition-level-classification).
"""

from services.ai_observation_prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    classify_recognition_level,
    strip_recognition_label_line,
)


def test_build_user_prompt_embeds_the_brand_name():
    prompt = build_user_prompt("サイボウズ")
    assert "「サイボウズ」" in prompt


def test_build_user_prompt_is_identical_for_the_same_brand_name_every_call():
    """The three observation providers (ChatGPT/Claude/Gemini) must
    ask the exact same question for the same brand — this is the
    property the whole unification exists for."""
    first = build_user_prompt("Acme")
    second = build_user_prompt("Acme")
    assert first == second


def test_build_user_prompt_differs_only_by_brand_name():
    acme_prompt = build_user_prompt("Acme")
    other_prompt = build_user_prompt("サイボウズ")
    assert acme_prompt.replace("Acme", "サイボウズ") == other_prompt


def test_build_user_prompt_forbids_web_search_and_discourages_guessing():
    """Task 6-D-1: must not encourage guessing business content purely
    from how the brand name sounds, and must forbid asserting unsure
    information as fact."""
    prompt = build_user_prompt("Acme")
    assert "Web検索や外部情報の取得は行わず" in prompt
    assert "名称の印象だけから事業内容や特徴を推測しないでください。" in prompt
    assert "不確かな情報は断定せず、不明な場合は不明としてください。" in prompt


def test_build_user_prompt_never_mentions_comparison_shopping_or_competitors():
    """Regression guard: the pre-unification Claude/Gemini prompt asked
    the model to imagine a comparison-shopping scenario and describe
    competitor/comparison context — removed in Task 6-C Review Prep 1
    per the project's confirmed policy against adding search-demand
    "おすすめ"/"選び方"-style research framing."""
    prompt = build_user_prompt("Acme")
    assert "比較検討する場面" not in prompt
    assert "競合" not in prompt


def test_system_prompt_forbids_web_search():
    assert "Web検索は行わず" in SYSTEM_PROMPT


def test_build_user_prompt_asks_for_the_recognition_label_line():
    """Task 6-D-1: the prompt must ask for a fixed, parseable
    self-report line so classify_recognition_level() has something to
    parse."""
    prompt = build_user_prompt("Acme")
    assert "認識レベル：" in prompt
    assert "具体的な認識あり" in prompt
    assert "部分的な認識" in prompt
    assert "対象企業を識別できない" in prompt
    assert "名称からの推測のみ" in prompt
    assert "判定不能" in prompt


# --- classify_recognition_level() -------------------------------------------


def test_classify_recognition_level_specific_knowledge():
    text = "Acmeは架空の企業で、SaaS事業を展開しています。\n認識レベル：具体的な認識あり"
    assert classify_recognition_level(text) == "specific_knowledge"


def test_classify_recognition_level_partial_knowledge():
    text = "Acmeについては一部の情報のみ把握しています。\n認識レベル：部分的な認識"
    assert classify_recognition_level(text) == "partial_knowledge"


def test_classify_recognition_level_unidentified():
    text = "Acmeという企業を具体的に識別できません。\n認識レベル：対象企業を識別できない"
    assert classify_recognition_level(text) == "unidentified"


def test_classify_recognition_level_name_inference_only():
    text = "名称から推測すると技術系の企業と思われます。\n認識レベル：名称からの推測のみ"
    assert classify_recognition_level(text) == "name_inference_only"


def test_classify_recognition_level_indeterminate_when_explicitly_reported():
    text = "判定できません。\n認識レベル：判定不能"
    assert classify_recognition_level(text) == "indeterminate"


def test_classify_recognition_level_falls_back_to_indeterminate_when_label_missing():
    """Task 6-D-1 "7": a parse failure must default to indeterminate,
    never be silently treated as recognized."""
    text = "Acmeについて説明します。特に目立った情報はありません。"
    assert classify_recognition_level(text) == "indeterminate"


def test_classify_recognition_level_falls_back_to_indeterminate_for_unparseable_label():
    text = "説明本文です。\n認識レベル：なんとも言えない"
    assert classify_recognition_level(text) == "indeterminate"


def test_classify_recognition_level_falls_back_to_indeterminate_for_empty_text():
    assert classify_recognition_level("") == "indeterminate"


def test_classify_recognition_level_tolerates_minor_formatting_drift():
    """Half-width colon, brackets, and surrounding whitespace are
    tolerated — but the match itself is still exact, never fuzzy."""
    assert classify_recognition_level("本文\n認識レベル:具体的な認識あり") == "specific_knowledge"
    assert classify_recognition_level("本文\n認識レベル：[判定不能]") == "indeterminate"


def test_classify_recognition_level_uses_the_last_matching_line():
    text = "認識レベル：具体的な認識あり\n本文がここに続きます。\n認識レベル：判定不能"
    assert classify_recognition_level(text) == "indeterminate"


# --- strip_recognition_label_line() -----------------------------------------


def test_strip_recognition_label_line_removes_the_trailing_label():
    text = "これは本文です。\n認識レベル：具体的な認識あり"
    assert strip_recognition_label_line(text) == "これは本文です。"


def test_strip_recognition_label_line_is_a_noop_when_label_missing():
    text = "これは本文です。ラベル行はありません。"
    assert strip_recognition_label_line(text) == text


def test_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str)
    assert PROMPT_VERSION


def test_chatgpt_claude_gemini_clients_all_call_the_same_build_user_prompt():
    """Task 6-D-1 requirement "1": ChatGPT/Claude/Gemini must continue
    to share one user-prompt-generation function. Verified by
    confirming each client module imports the exact same function
    object from this module (rather than a module-local copy)."""
    from services import chatgpt_client, claude_client, gemini_client

    assert chatgpt_client.build_user_prompt is build_user_prompt
    assert claude_client.build_user_prompt is build_user_prompt
    assert gemini_client.build_user_prompt is build_user_prompt
