from services.history_mode_summary import build_mode_summary


def test_returns_unknown_for_every_field_when_meta_is_none():
    assert build_mode_summary(None) == {
        "aiOverview": "unknown",
        "chatgpt": "unknown",
        "claude": "unknown",
        "gemini": "unknown",
        "commonCrawl": "unknown",
    }


def test_returns_unknown_for_every_field_when_meta_is_empty_dict():
    assert build_mode_summary({}) == {
        "aiOverview": "unknown",
        "chatgpt": "unknown",
        "claude": "unknown",
        "gemini": "unknown",
        "commonCrawl": "unknown",
    }


def test_chatgpt_claude_gemini_common_crawl_use_status_directly():
    meta = {
        "chatgptProvider": {"mode": "openai", "status": "real", "reason": "ok"},
        "claudeProvider": {"mode": "off", "status": "off", "reason": "disabled"},
        "geminiProvider": {"mode": "google", "status": "unavailable", "reason": "no key"},
        "commonCrawlProvider": {"mode": "domain", "status": "real", "reason": "ok"},
    }

    summary = build_mode_summary(meta)

    assert summary["chatgpt"] == "real"
    assert summary["claude"] == "off"
    assert summary["gemini"] == "unavailable"
    assert summary["commonCrawl"] == "real"


def test_ai_overview_uses_environment_when_present():
    meta = {
        "aiOverviewProvider": {
            "mode": "dataforseo_live",
            "status": "real",
            "reason": "ok",
            "environment": "live",
        }
    }

    assert build_mode_summary(meta)["aiOverview"] == "live"


def test_ai_overview_falls_back_to_off_mode_without_environment():
    meta = {"aiOverviewProvider": {"mode": "off", "status": "off", "reason": "disabled"}}

    assert build_mode_summary(meta)["aiOverview"] == "off"


def test_ai_overview_falls_back_to_mock_mode_without_environment():
    meta = {"aiOverviewProvider": {"mode": "mock", "status": "mock", "reason": "mock data"}}

    assert build_mode_summary(meta)["aiOverview"] == "mock"


def test_ai_overview_falls_back_to_sandbox_for_old_real_dataforseo_without_environment():
    # A saved run from before AIOverviewProviderInfo.environment existed —
    # mode="dataforseo" + status="real" with no "environment" key at all.
    meta = {"aiOverviewProvider": {"mode": "dataforseo", "status": "real", "reason": "ok"}}

    assert build_mode_summary(meta)["aiOverview"] == "sandbox"


def test_ai_overview_falls_back_to_unavailable_for_old_failed_dataforseo_without_environment():
    meta = {
        "aiOverviewProvider": {
            "mode": "dataforseo",
            "status": "unavailable",
            "reason": "no credentials",
        }
    }

    assert build_mode_summary(meta)["aiOverview"] == "unavailable"


def test_partial_meta_only_marks_missing_providers_unknown():
    meta = {"chatgptProvider": {"mode": "openai", "status": "real", "reason": "ok"}}

    summary = build_mode_summary(meta)

    assert summary["chatgpt"] == "real"
    assert summary["aiOverview"] == "unknown"
    assert summary["claude"] == "unknown"
    assert summary["gemini"] == "unknown"
    assert summary["commonCrawl"] == "unknown"


def test_provider_present_but_falsy_status_is_unknown():
    # Defensive: a provider dict with no usable "status" key at all
    # (shouldn't happen from real AnalysisMeta, but must not raise).
    meta = {"claudeProvider": {"mode": "off"}}

    assert build_mode_summary(meta)["claude"] == "unknown"
