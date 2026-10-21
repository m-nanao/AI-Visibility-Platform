"""Task 6-D-1 (feature/recognition-level-classification) backward
compatibility: analysis history saved before this task's
recognitionLevel/promptVersion fields existed must still parse
successfully, with both new fields defaulting to None.
"""

from models import ChatGptProviderInfo, ClaudeProviderInfo, GeminiProviderInfo


def test_chatgpt_provider_info_parses_a_pre_task_6d1_history_row():
    old_meta = {
        "mode": "openai",
        "status": "real",
        "reason": "ChatGPT OpenAI API request succeeded.",
        "environment": "api",
    }
    info = ChatGptProviderInfo.model_validate(old_meta)
    assert info.recognitionLevel is None
    assert info.promptVersion is None


def test_claude_provider_info_parses_a_pre_task_6d1_history_row():
    old_meta = {
        "mode": "anthropic",
        "status": "real",
        "reason": "Claude Anthropic API request succeeded.",
        "environment": "api",
    }
    info = ClaudeProviderInfo.model_validate(old_meta)
    assert info.recognitionLevel is None
    assert info.promptVersion is None


def test_gemini_provider_info_parses_a_pre_task_6d1_history_row():
    old_meta = {
        "mode": "google",
        "status": "real",
        "reason": "Gemini Google API request succeeded.",
        "environment": "api",
    }
    info = GeminiProviderInfo.model_validate(old_meta)
    assert info.recognitionLevel is None
    assert info.promptVersion is None


def test_chatgpt_provider_info_round_trips_the_new_fields_when_present():
    info = ChatGptProviderInfo.model_validate(
        {
            "mode": "openai",
            "status": "real",
            "reason": "ChatGPT OpenAI API request succeeded.",
            "environment": "api",
            "recognitionLevel": "specific_knowledge",
            "promptVersion": "no_search_v1",
        }
    )
    assert info.recognitionLevel == "specific_knowledge"
    assert info.promptVersion == "no_search_v1"
