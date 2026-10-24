"""Tests for services/analysis_supplement_orchestrator.py's
run_sync_supplement_providers() (Task 6-D-5C-4B,
feature/shared-analysis-supplement-orchestrator).

This is a pure extraction of the block that used to live inline in
backend/main.py's _analyze_authenticated_idempotent() — these tests
exercise the orchestrator function directly (not through the FastAPI
route; that wiring is already covered by
tests/test_main_chatgpt_websearch_supplement.py,
tests/test_main_claude_websearch_supplement.py,
tests/test_main_gemini_websearch_supplement.py, and
tests/test_main_gemini_external_document_supplement.py, which were
updated by this task to monkeypatch
services.analysis_supplement_orchestrator instead of main.py directly).

Never touches a real database and never calls a real external
provider: all four `attempt_*_supplement` functions are monkeypatched
at this module's own namespace.
"""

import services.analysis_supplement_orchestrator as orchestrator
from models import (
    AIOverviewComparisonItem,
    ChatGptProviderInfo,
    ChatGptWebsearchProviderInfo,
    ClaudeProviderInfo,
    ClaudeWebsearchProviderInfo,
    GeminiExternalDocumentProviderInfo,
    GeminiProviderInfo,
    GeminiWebsearchProviderInfo,
)
from services.mock_analysis import build_dummy_analysis

ANALYSIS_RUN_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"


def _result_with_recognition_levels(
    *, chatgpt: str | None = None, claude: str | None = None, gemini: str | None = None
):
    result = build_dummy_analysis("Acme")
    if chatgpt is not None:
        result.meta.chatgptProvider = ChatGptProviderInfo(
            mode="openai", status="real", reason="ok", environment="api",
            recognitionLevel=chatgpt, promptVersion="no_search_v1",
        )
    if claude is not None:
        result.meta.claudeProvider = ClaudeProviderInfo(
            mode="anthropic", status="real", reason="ok", environment="api",
            recognitionLevel=claude, promptVersion="no_search_v1",
        )
    if gemini is not None:
        result.meta.geminiProvider = GeminiProviderInfo(
            mode="google", status="real", reason="ok", environment="api",
            recognitionLevel=gemini, promptVersion="no_search_v1",
        )
    return result


def _not_attempted_infos():
    """Disabled-by-default info objects — used for the three providers
    not under test in a given test, so each test can isolate exactly
    one provider's behavior."""
    return {
        "attempt_chatgpt_websearch_supplement": lambda **kw: (
            None, ChatGptWebsearchProviderInfo(status="disabled", reason="disabled")
        ),
        "attempt_claude_websearch_supplement": lambda **kw: (
            None, ClaudeWebsearchProviderInfo(status="disabled", reason="disabled")
        ),
        "attempt_gemini_websearch_supplement": lambda **kw: (
            None, GeminiWebsearchProviderInfo(status="disabled", reason="disabled")
        ),
        "attempt_gemini_external_document_supplement": lambda **kw: (
            None, GeminiExternalDocumentProviderInfo(status="disabled", reason="disabled")
        ),
    }


def _patch_all_not_attempted(monkeypatch, overrides=None):
    fakes = _not_attempted_infos()
    fakes.update(overrides or {})
    for name, fn in fakes.items():
        monkeypatch.setattr(orchestrator, name, fn)


def _run(result, *, documents=None, async_worker_id=None):
    orchestrator.run_sync_supplement_providers(
        brand_name="Acme",
        result=result,
        web_fetch_documents=documents or [],
        analysis_run_id=ANALYSIS_RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
        async_worker_id=async_worker_id,
    )
    return result


# --- all four OFF ----------------------------------------------------------


def test_all_four_disabled_leaves_aioverviewcomparison_unchanged(monkeypatch):
    result = _result_with_recognition_levels(chatgpt="unidentified", claude="unidentified", gemini="unidentified")
    before_count = len(result.aiOverviewComparison)
    _patch_all_not_attempted(monkeypatch)

    _run(result)

    assert len(result.aiOverviewComparison) == before_count
    assert result.meta.chatgptWebsearchProvider.status == "disabled"
    assert result.meta.claudeWebsearchProvider.status == "disabled"
    assert result.meta.geminiWebsearchProvider.status == "disabled"
    assert result.meta.geminiExternalDocumentProvider.status == "disabled"


# --- each ON individually ---------------------------------------------------


def test_chatgpt_websearch_on_appends_item_and_calls_with_right_args(monkeypatch):
    result = _result_with_recognition_levels(chatgpt="unidentified")
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        item = AIOverviewComparisonItem(
            platform="ChatGPT (OpenAI API, Web検索補完)", mentioned=True, rank=None,
            summary="s", observationMethod="websearch_supplement",
        )
        return item, ChatGptWebsearchProviderInfo(status="real", reason="ok", searched=True)

    _patch_all_not_attempted(monkeypatch, {"attempt_chatgpt_websearch_supplement": fake})

    before_count = len(result.aiOverviewComparison)
    _run(result)

    assert len(result.aiOverviewComparison) == before_count + 1
    assert result.meta.chatgptWebsearchProvider.status == "real"
    assert calls[0]["recognition_level"] == "unidentified"
    assert calls[0]["analysis_run_id"] == ANALYSIS_RUN_ID
    assert calls[0]["project_id"] == PROJECT_ID
    assert calls[0]["user_id"] == USER_ID


def test_claude_websearch_on_appends_item(monkeypatch):
    result = _result_with_recognition_levels(claude="partial_knowledge")

    def fake(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Claude (Anthropic API, Web検索補完)", mentioned=True, rank=None,
            summary="s", observationMethod="websearch_supplement",
        )
        return item, ClaudeWebsearchProviderInfo(status="real", reason="ok", searched=True)

    _patch_all_not_attempted(monkeypatch, {"attempt_claude_websearch_supplement": fake})

    before_count = len(result.aiOverviewComparison)
    _run(result)

    assert len(result.aiOverviewComparison) == before_count + 1
    assert result.meta.claudeWebsearchProvider.status == "real"


def test_gemini_websearch_grounding_default_off_stays_off_even_when_orchestrated(monkeypatch):
    """Task 6-D-5C-4B §6 (special note): Google Search grounding must
    remain default-disabled; this orchestrator never loosens that
    gate. Here the real (unmocked) attempt_gemini_websearch_supplement
    is used (only the other three are stubbed) to prove the real
    default-disabled code path is reached unchanged — no monkeypatch
    of its own gate logic."""
    result = _result_with_recognition_levels(gemini="unidentified")
    monkeypatch.delenv("GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED", raising=False)
    other_fakes = _not_attempted_infos()
    del other_fakes["attempt_gemini_websearch_supplement"]
    for name, fn in other_fakes.items():
        monkeypatch.setattr(orchestrator, name, fn)

    before_count = len(result.aiOverviewComparison)
    _run(result)

    assert len(result.aiOverviewComparison) == before_count
    assert result.meta.geminiWebsearchProvider.status == "disabled"


def test_gemini_external_document_on_appends_item_with_documents(monkeypatch):
    from models import Document

    result = _result_with_recognition_levels(gemini="unidentified")
    docs = [
        Document(
            id="doc-1",
            sourceType="web_fetch",
            sourceUrl="https://acme.example.com",
            fetchedAt="2026-10-24T00:00:00Z",
            text="hello",
        )
    ]
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        item = AIOverviewComparisonItem(
            platform="Gemini (Google API, 外部文書補完)", mentioned=True, rank=None,
            summary="s", observationMethod="external_document_supplement",
        )
        return item, GeminiExternalDocumentProviderInfo(status="real", reason="ok")

    _patch_all_not_attempted(monkeypatch, {"attempt_gemini_external_document_supplement": fake})

    before_count = len(result.aiOverviewComparison)
    _run(result, documents=docs)

    assert len(result.aiOverviewComparison) == before_count + 1
    assert calls[0]["documents"] == docs


# --- multiple ON simultaneously, in the original fixed order --------------


def test_multiple_supplements_on_append_in_fixed_order_and_are_independent(monkeypatch):
    result = _result_with_recognition_levels(chatgpt="unidentified", claude="unidentified", gemini="unidentified")

    def fake_chatgpt(**kwargs):
        item = AIOverviewComparisonItem(
            platform="ChatGPT (OpenAI API, Web検索補完)", mentioned=True, rank=None,
            summary="chatgpt", observationMethod="websearch_supplement",
        )
        return item, ChatGptWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_claude(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Claude (Anthropic API, Web検索補完)", mentioned=True, rank=None,
            summary="claude", observationMethod="websearch_supplement",
        )
        return item, ClaudeWebsearchProviderInfo(status="real", reason="ok", searched=True)

    def fake_gemini_external_document(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Gemini (Google API, 外部文書補完)", mentioned=True, rank=None,
            summary="gemini-doc", observationMethod="external_document_supplement",
        )
        return item, GeminiExternalDocumentProviderInfo(status="real", reason="ok")

    _patch_all_not_attempted(
        monkeypatch,
        {
            "attempt_chatgpt_websearch_supplement": fake_chatgpt,
            "attempt_claude_websearch_supplement": fake_claude,
            "attempt_gemini_external_document_supplement": fake_gemini_external_document,
        },
    )

    before_count = len(result.aiOverviewComparison)
    _run(result)

    new_items = result.aiOverviewComparison[before_count:]
    assert [item.summary for item in new_items] == ["chatgpt", "claude", "gemini-doc"]
    assert result.meta.geminiWebsearchProvider.status == "disabled"


# --- failure isolation -------------------------------------------------------


def test_one_provider_exception_never_affects_the_others(monkeypatch):
    result = _result_with_recognition_levels(chatgpt="unidentified", claude="unidentified")

    def raises(**kwargs):
        raise RuntimeError("boom")

    def fake_claude(**kwargs):
        item = AIOverviewComparisonItem(
            platform="Claude (Anthropic API, Web検索補完)", mentioned=True, rank=None,
            summary="claude", observationMethod="websearch_supplement",
        )
        return item, ClaudeWebsearchProviderInfo(status="real", reason="ok", searched=True)

    _patch_all_not_attempted(
        monkeypatch,
        {"attempt_chatgpt_websearch_supplement": raises, "attempt_claude_websearch_supplement": fake_claude},
    )

    before_count = len(result.aiOverviewComparison)
    # Must not raise.
    _run(result)

    new_items = result.aiOverviewComparison[before_count:]
    assert [item.summary for item in new_items] == ["claude"]
    # chatgpt's meta field is simply never set when the provider call
    # itself raises before returning — mirrors the original inline
    # code's behavior (the try/except wraps the whole block, including
    # the assignment to result.meta.chatgptWebsearchProvider).
    assert result.meta.chatgptWebsearchProvider is None
    assert result.meta.claudeWebsearchProvider.status == "real"


def test_provider_timeout_like_exception_is_isolated_too(monkeypatch):
    """A provider's own HTTP client raising a timeout-shaped exception
    must be swallowed exactly like any other unexpected exception —
    this orchestrator does not special-case timeouts."""
    result = _result_with_recognition_levels(gemini="unidentified")

    class FakeTimeout(Exception):
        pass

    def raises_timeout(**kwargs):
        raise FakeTimeout("timed out")

    _patch_all_not_attempted(
        monkeypatch, {"attempt_gemini_external_document_supplement": raises_timeout}
    )

    before_count = len(result.aiOverviewComparison)
    _run(result)

    assert len(result.aiOverviewComparison) == before_count
    assert result.meta.geminiExternalDocumentProvider is None


# --- quota rejection is passed through unchanged, never bypassed ----------


def test_quota_rejected_status_is_not_treated_as_an_error_and_no_item_is_appended(monkeypatch):
    """The orchestrator must never add a fallback that calls a
    provider's API when its own quota reservation failed — the
    provider itself returns (None, info with a rejection status), and
    this must simply result in no appended item, same as any other
    "not attempted" outcome."""
    result = _result_with_recognition_levels(chatgpt="unidentified")

    def fake(**kwargs):
        return None, ChatGptWebsearchProviderInfo(
            status="quota_rejected", reason="daily/monthly quota exceeded"
        )

    _patch_all_not_attempted(monkeypatch, {"attempt_chatgpt_websearch_supplement": fake})

    before_count = len(result.aiOverviewComparison)
    _run(result)

    assert len(result.aiOverviewComparison) == before_count
    assert result.meta.chatgptWebsearchProvider.status == "quota_rejected"


# --- backward compatibility: result format unchanged ------------------------


def test_result_shape_matches_original_inline_code_fields():
    """No new top-level fields are introduced by this refactor — the
    orchestrator only ever touches the same four
    result.meta.*WebsearchProvider / geminiExternalDocumentProvider
    fields and result.aiOverviewComparison, exactly as the original
    inline code in main.py did."""
    result = build_dummy_analysis("Acme")
    assert hasattr(result.meta, "chatgptWebsearchProvider")
    assert hasattr(result.meta, "claudeWebsearchProvider")
    assert hasattr(result.meta, "geminiWebsearchProvider")
    assert hasattr(result.meta, "geminiExternalDocumentProvider")
    # factExtraction is untouched by this orchestrator (Task 6-D-5C-4B
    # explicitly excludes FactExtraction from this refactor).
    assert result.factExtraction is None


# --- Task 6-D-5C-4G: async_worker_id wiring --------------------------------


def test_async_worker_id_defaults_to_none_for_every_provider(monkeypatch):
    """The synchronous caller (backend/main.py) never passes this
    kwarg — confirms the default (None) reaches all four providers
    unchanged."""
    result = _result_with_recognition_levels(chatgpt="unidentified", claude="unidentified", gemini="unidentified")
    calls: dict[str, dict] = {}

    def make_recorder(name):
        def recorder(**kwargs):
            calls[name] = kwargs
            return None, type("Info", (), {"status": "disabled", "reason": "ok"})()

        return recorder

    for name in (
        "attempt_chatgpt_websearch_supplement",
        "attempt_claude_websearch_supplement",
        "attempt_gemini_websearch_supplement",
        "attempt_gemini_external_document_supplement",
    ):
        monkeypatch.setattr(orchestrator, name, make_recorder(name))

    _run(result)

    assert all(calls[name]["async_worker_id"] is None for name in calls)
    assert len(calls) == 4


def test_async_worker_id_is_threaded_through_to_every_provider_when_given(monkeypatch):
    result = _result_with_recognition_levels(chatgpt="unidentified", claude="unidentified", gemini="unidentified")
    calls: dict[str, dict] = {}

    def make_recorder(name):
        def recorder(**kwargs):
            calls[name] = kwargs
            return None, type("Info", (), {"status": "disabled", "reason": "ok"})()

        return recorder

    for name in (
        "attempt_chatgpt_websearch_supplement",
        "attempt_claude_websearch_supplement",
        "attempt_gemini_websearch_supplement",
        "attempt_gemini_external_document_supplement",
    ):
        monkeypatch.setattr(orchestrator, name, make_recorder(name))

    _run(result, async_worker_id="worker-1")

    assert all(calls[name]["async_worker_id"] == "worker-1" for name in calls)
    assert len(calls) == 4
