"""Tests for services/ai_observation_prompts.py's build_user_prompt()
— the single shared user-prompt generator ChatGPT/Claude/Gemini all
call as of Task 6-C Review Prep 1 (feature/unify-ai-observation-prompts).
"""

from services.ai_observation_prompts import SYSTEM_PROMPT, build_user_prompt


def test_build_user_prompt_embeds_the_brand_name():
    prompt = build_user_prompt("サイボウズ")
    assert "ブランド名：サイボウズ" in prompt


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
    prompt = build_user_prompt("Acme")
    assert "Web検索は行わず" in prompt
    assert "確信できない情報は推測で補わず、不明であることを明示してください。" in prompt


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
