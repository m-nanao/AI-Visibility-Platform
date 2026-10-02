"""Verifies services/gemini_rerun.py's rerun_gemini_for_analysis_run() —
the pure logic behind POST /analysis-runs/{id}/rerun/gemini (see
tests/test_main_analysis_runs_rerun_gemini_api.py for the HTTP-level
wiring). build_gemini_observation() itself (the actual Gemini API call)
is monkeypatched directly here — its own behavior is already covered by
tests/test_gemini_provider.py and tests/test_gemini_client.py — so these
tests focus on what rerun_gemini_for_analysis_run() does with the
result: which card gets replaced/added, which fields stay untouched,
and that a failure never touches result_json/meta_json at all.
"""

from models import AIOverviewComparisonItem
from services import gemini_rerun
from services.gemini_provider import GEMINI_PLATFORM_LABEL


def _gemini_card(**overrides) -> dict:
    card = {
        "platform": GEMINI_PLATFORM_LABEL,
        "mentioned": True,
        "rank": None,
        "summary": "old Gemini summary",
        "fullSummary": "old Gemini full summary",
        "isTruncated": True,
        "note": "Gemini APIの出力が途中で終了した可能性があります。",
    }
    card.update(overrides)
    return card


def _chatgpt_card() -> dict:
    return {
        "platform": "ChatGPT (OpenAI API)",
        "mentioned": True,
        "rank": None,
        "summary": "chatgpt summary",
    }


def _mock_successful_gemini_call(monkeypatch, *, mentioned=True, summary="new Gemini summary"):
    new_item = AIOverviewComparisonItem(
        platform=GEMINI_PLATFORM_LABEL,
        mentioned=mentioned,
        rank=None,
        summary=summary,
        fullSummary=summary,
        isTruncated=False,
        note=None,
    )
    monkeypatch.setattr(
        gemini_rerun,
        "build_gemini_observation",
        lambda brand_name, mode: (new_item, "real", "ok", "api"),
    )
    return new_item


def _mock_failed_gemini_call(monkeypatch, reason: str = "Gemini API key is not configured."):
    monkeypatch.setattr(
        gemini_rerun,
        "build_gemini_observation",
        lambda brand_name, mode: (None, "unavailable", reason, "unavailable"),
    )


def _mock_resolve_mode(monkeypatch, mode: str = "google"):
    monkeypatch.setattr(gemini_rerun, "resolve_gemini_mode", lambda override: mode)


def test_success_replaces_existing_gemini_card(monkeypatch):
    _mock_resolve_mode(monkeypatch)
    new_item = _mock_successful_gemini_call(monkeypatch, summary="fresh text")

    result_json = {
        "aiOverviewComparison": [_chatgpt_card(), _gemini_card()],
        "cooccurrenceRanking": [],
    }

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={"geminiMode": "google"},
        result_json=result_json,
        meta_json={},
    )

    assert outcome.success is True
    cards = outcome.result_json["aiOverviewComparison"]
    assert len(cards) == 2
    assert cards[0]["platform"] == "ChatGPT (OpenAI API)"
    assert cards[1]["platform"] == GEMINI_PLATFORM_LABEL
    assert cards[1]["summary"] == "fresh text"
    assert cards[1] == new_item.model_dump()


def test_success_adds_gemini_card_when_none_existed_before(monkeypatch):
    _mock_resolve_mode(monkeypatch)
    _mock_successful_gemini_call(monkeypatch)

    result_json = {
        "aiOverviewComparison": [_chatgpt_card()],
        "cooccurrenceRanking": [],
    }

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={},
        result_json=result_json,
        meta_json={},
    )

    assert outcome.success is True
    platforms = [card["platform"] for card in outcome.result_json["aiOverviewComparison"]]
    assert platforms == ["ChatGPT (OpenAI API)", GEMINI_PLATFORM_LABEL]


def test_success_updates_gemini_provider_in_meta(monkeypatch):
    _mock_resolve_mode(monkeypatch, "google")
    _mock_successful_gemini_call(monkeypatch)

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={},
        result_json={"aiOverviewComparison": []},
        meta_json={"chatgptProvider": {"mode": "openai"}},
    )

    assert outcome.success is True
    # Only geminiProvider is touched — every other meta_json field
    # (e.g. chatgptProvider) is left exactly as it was.
    assert outcome.meta_json["chatgptProvider"] == {"mode": "openai"}
    assert outcome.meta_json["geminiProvider"] == {
        "mode": "google",
        "status": "real",
        "reason": "ok",
        "environment": "api",
    }


def test_failure_never_touches_result_json_or_meta_json(monkeypatch):
    _mock_resolve_mode(monkeypatch)
    _mock_failed_gemini_call(monkeypatch, reason="Gemini API key is not configured.")

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={},
        result_json={"aiOverviewComparison": [_gemini_card()]},
        meta_json={"geminiProvider": {"mode": "off"}},
    )

    assert outcome.success is False
    assert outcome.reason == "Gemini API key is not configured."
    assert outcome.result_json is None
    assert outcome.meta_json is None


def test_failure_reason_never_contains_credential_like_text(monkeypatch):
    # A defensive check: whatever reason build_gemini_observation
    # returns is passed straight through to the HTTP response body (see
    # main.py's rerun endpoint) — this only asserts the specific
    # messages this module is known to forward don't look like a key.
    _mock_resolve_mode(monkeypatch)
    _mock_failed_gemini_call(monkeypatch, reason="Gemini request limit must be 1.")

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme", input_snapshot={}, result_json={}, meta_json={}
    )

    assert "key" not in outcome.reason.lower() or "not configured" in outcome.reason.lower()


def test_resolves_mode_from_saved_input_snapshot(monkeypatch):
    received_overrides = []
    monkeypatch.setattr(
        gemini_rerun,
        "resolve_gemini_mode",
        lambda override: received_overrides.append(override) or "google",
    )
    _mock_successful_gemini_call(monkeypatch)

    gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={"geminiMode": "google", "brandName": "Acme"},
        result_json={"aiOverviewComparison": []},
        meta_json={},
    )

    assert received_overrides == ["google"]


def test_resolves_mode_with_none_override_when_input_snapshot_missing(monkeypatch):
    received_overrides = []
    monkeypatch.setattr(
        gemini_rerun,
        "resolve_gemini_mode",
        lambda override: received_overrides.append(override) or "google",
    )
    _mock_successful_gemini_call(monkeypatch)

    gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot=None,
        result_json={"aiOverviewComparison": []},
        meta_json={},
    )

    assert received_overrides == [None]


def test_webaigap_is_left_untouched_when_absent(monkeypatch):
    _mock_resolve_mode(monkeypatch)
    _mock_successful_gemini_call(monkeypatch)

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={},
        result_json={"aiOverviewComparison": []},
        meta_json={},
    )

    assert outcome.success is True
    assert outcome.result_json["webAiGap"] is None


def test_webaigap_rebuild_failure_falls_back_to_existing_value(monkeypatch):
    _mock_resolve_mode(monkeypatch)
    _mock_successful_gemini_call(monkeypatch)

    malformed_web_ai_gap = {"status": "real"}  # missing required `note` field

    outcome = gemini_rerun.rerun_gemini_for_analysis_run(
        brand_name="Acme",
        input_snapshot={},
        result_json={"aiOverviewComparison": [], "webAiGap": malformed_web_ai_gap},
        meta_json={},
    )

    assert outcome.success is True
    assert outcome.result_json["webAiGap"] == malformed_web_ai_gap
