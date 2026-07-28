import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from main import app
from models import (
    MAX_DOCUMENT_LENGTH,
    MAX_DOCUMENTS_COUNT,
    MAX_TOTAL_DOCUMENTS_LENGTH,
    MAX_URLS,
    AnalysisResult,
)
from services import chatgpt_client, common_crawl_index, common_crawl_warc, dataforseo_client
from services.sample_documents import SAMPLE_DOCUMENT_TEMPLATES
from services.web_fetcher import UrlFetchResult as FetcherResult

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_construct_janome_tokenizer():
    """/health must stay independent of analysis processing.

    Runs in a fresh subprocess (importing main + calling /health only)
    so this reflects the actual FastAPI startup path on Render, where
    a heavy import/init here previously caused an out-of-memory crash
    before uvicorn could even bind the port.
    """
    script = (
        "import sys; "
        "from fastapi.testclient import TestClient; "
        "from main import app; "
        "response = TestClient(app).get('/health'); "
        "assert response.status_code == 200; "
        "assert 'janome.tokenizer' not in sys.modules, "
        "'/health must not trigger Janome Tokenizer initialization'"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
    )


def test_analyze_does_not_construct_janome_tokenizer_by_default():
    """/analyze must also stay off Janome by default, not just /health.

    The startup fix (lazy Tokenizer construction) alone wasn't enough
    to prevent Render free-tier 502/timeout: /analyze's first real
    call was still what triggered the Janome dictionary load, just
    delayed from startup to request time. TOKENIZER_MODE defaults to
    "simple" (regex-based, no dictionary) precisely so this never
    happens unless an operator opts in via TOKENIZER_MODE=janome.
    """
    script = (
        "import sys; "
        "from fastapi.testclient import TestClient; "
        "from main import app; "
        "response = TestClient(app).post('/analyze', json={'brandName': 'OpenAI'}); "
        "assert response.status_code == 200; "
        "assert 'janome.tokenizer' not in sys.modules, "
        "'/analyze must not trigger Janome Tokenizer initialization by default'"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
    )


def test_analyze_returns_200_for_valid_brand_name():
    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200


def test_analyze_response_matches_analysis_result_shape():
    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    # Re-parsing the raw JSON through the Pydantic model raises
    # ValidationError if the response doesn't actually match AnalysisResult.
    result = AnalysisResult.model_validate(response.json())
    assert result.brandName == "OpenAI"
    # cooccurrenceRanking, contextAnalysis, summary, and improvements
    # are always genuinely computed (from caller-supplied documents/
    # urls, or development sample documents), but aiOverviewComparison
    # is still fixed placeholder data.
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.sections.summary == "real"
    assert result.meta.sections.contextAnalysis == "real"
    assert result.meta.sections.aiOverviewComparison == "mock"
    assert result.meta.sections.improvements == "real"
    assert result.meta.documentsSource == "development_sample"
    assert len(result.contextAnalysis) > 0
    assert result.summary.brandName == "OpenAI"
    assert 0 <= result.summary.visibilityScore <= 100
    assert len(result.improvements) > 0


def test_analyze_computes_cooccurrence_ranking_from_provided_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": [
                "OpenAIの料金プランについて教えてください。",
                "OpenAIの料金プランはとても安いです。",
            ],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentsSource == "user_provided"
    counts = {kw.keyword: kw.count for kw in result.cooccurrenceRanking}
    assert counts["料金"] == 2
    assert counts["プラン"] == 2


def test_analyze_computes_context_analysis_from_provided_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": [
                "OpenAIの料金プランについて教えてください。",
                "OpenAIのサポートへの問い合わせはとても迅速です。",
            ],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.contextAnalysis == "real"
    assert len(result.contextAnalysis) > 0
    labels = {item.context for item in result.contextAnalysis}
    assert "料金・価格" in labels


def test_analyze_computes_brand_summary_from_provided_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": [
                "OpenAIの料金プランについて教えてください。",
                "OpenAIの料金プランはとても安いです。",
            ],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.summary == "real"
    assert result.summary.brandName == "OpenAI"
    # brandName appears twice above, once per document.
    assert result.summary.totalMentions == 2
    breakdown = result.summary.sentimentBreakdown
    assert breakdown.positive + breakdown.neutral + breakdown.negative == 100
    # documents came from user_provided text, not real AI platforms —
    # topPlatforms must not claim ChatGPT/Perplexity/etc. were measured.
    unmeasured_platform_names = {"ChatGPT", "Perplexity", "Google AI Overview", "Copilot"}
    assert not unmeasured_platform_names.intersection(result.summary.topPlatforms)
    # aiOverviewComparison remains mock even though summary is now real.
    assert result.meta.sections.aiOverviewComparison == "mock"


def test_analyze_computes_improvement_suggestions_from_provided_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": [
                "OpenAIの料金プランについて教えてください。",
                "OpenAIの料金プランはとても安いです。",
            ],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.improvements == "real"
    assert len(result.improvements) > 0
    # No context category besides pricing was surfaced by these two
    # documents, so at least one missing-category suggestion (e.g. use
    # case) should be raised, each carrying its own reason.
    for suggestion in result.improvements:
        assert suggestion.description
        assert suggestion.priority in ("high", "medium", "low")
    titles = [s.title for s in result.improvements]
    assert len(titles) == len(set(titles))
    # aiOverviewComparison remains mock even though improvements is now real.
    assert result.meta.sections.aiOverviewComparison == "mock"


def test_analyze_default_ai_overview_mode_is_mock(monkeypatch):
    monkeypatch.delenv("AI_OVERVIEW_PROVIDER_MODE", raising=False)
    monkeypatch.delenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", raising=False)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "mock"
    assert len(result.aiOverviewComparison) > 0
    assert result.meta.aiOverviewProvider is not None
    assert result.meta.aiOverviewProvider.mode == "mock"
    assert result.meta.aiOverviewProvider.status == "mock"
    # The other sections must stay real and unaffected by aiOverviewComparison's mode.
    assert result.meta.sections.summary == "real"
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.sections.contextAnalysis == "real"
    assert result.meta.sections.improvements == "real"


def test_analyze_ai_overview_mode_off_returns_unavailable_and_empty(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "unavailable"
    assert result.aiOverviewComparison == []
    assert result.meta.aiOverviewProvider is not None
    assert result.meta.aiOverviewProvider.mode == "off"
    assert result.meta.aiOverviewProvider.status == "unavailable"
    # The other sections must stay real and unaffected.
    assert result.meta.sections.summary == "real"
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.sections.contextAnalysis == "real"
    assert result.meta.sections.improvements == "real"


def test_analyze_ai_overview_mode_dataforseo_returns_unavailable_without_credentials(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without DataForSEO credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "unavailable"
    assert result.aiOverviewComparison == []
    assert result.meta.aiOverviewProvider is not None
    assert result.meta.aiOverviewProvider.mode == "dataforseo"
    assert result.meta.aiOverviewProvider.status == "unavailable"
    assert result.meta.aiOverviewProvider.environment == "unavailable"
    assert "not configured" in result.meta.aiOverviewProvider.reason


def test_analyze_ai_overview_mode_dataforseo_live_env_without_confirm_text_is_rejected_safely(monkeypatch):
    # No httpx mocking here on purpose: this test documents that the
    # Live host is never reached when the manual confirmation gates
    # aren't all satisfied (DATAFORSEO_LIVE_CONFIRM_TEXT is left unset
    # here), by asserting on the rejection reason — which is decided
    # entirely by env vars, before any HTTP call would be attempted.
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.environment == "unavailable"
    reason = result.meta.aiOverviewProvider.reason
    assert "Live API" in reason
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason
    # The password/login must not leak anywhere else in the response either.
    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "someone@example.com" not in raw_body


def test_analyze_ai_overview_mode_dataforseo_live_env_with_all_gates_satisfied_is_reflected_in_response(
    monkeypatch,
):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "ALLOW_DATAFORSEO_LIVE_ONCE")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    payload = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {"type": "ai_overview", "rank_absolute": 1, "markdown": "OpenAI is a well-known AI lab."}
                        ]
                    }
                ]
            }
        ],
    }

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    assert seen_urls == ["https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"]

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "real"
    assert result.meta.aiOverviewProvider.status == "real"
    assert result.meta.aiOverviewProvider.environment == "live"
    assert len(result.aiOverviewComparison) == 1
    assert result.aiOverviewComparison[0].platform == "Google AI Mode (DataForSEO Live)"
    assert result.aiOverviewComparison[0].mentioned is True
    # credentials never leak into the response body.
    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "someone@example.com" not in raw_body


def test_analyze_ai_overview_mode_dataforseo_sandbox_success_is_reflected_in_response(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {"type": "ai_overview", "rank_absolute": 1, "text": "OpenAI is a well-known AI lab."}
                        ]
                    }
                ]
            }
        ],
    }

    def fake_post(url, **kwargs):
        assert "sandbox.dataforseo.com" in url
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "real"
    assert len(result.aiOverviewComparison) == 1
    assert result.aiOverviewComparison[0].mentioned is True
    assert result.meta.aiOverviewProvider.status == "real"
    assert result.meta.aiOverviewProvider.environment == "sandbox"
    # Other real sections must be unaffected by aiOverviewComparison's mode.
    assert result.meta.sections.summary == "real"
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.sections.contextAnalysis == "real"
    assert result.meta.sections.improvements == "real"


def test_analyze_ai_overview_mode_dataforseo_uses_ai_mode_endpoint_by_default(monkeypatch):
    # Mirrors the shape manually confirmed against DataForSEO Sandbox's
    # AI Mode endpoint (see docs/07_decisions.md): item_types includes
    # "ai_overview", and the item carries markdown + references rather
    # than a plain "text" field.
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "item_types": ["ai_overview"],
                        "items_count": 1,
                        "items": [
                            {
                                "type": "ai_overview",
                                "rank_group": 1,
                                "markdown": "OpenAI is a well-known AI lab that builds ChatGPT.",
                                "references": [
                                    {"title": "OpenAI", "domain": "openai.com", "text": "Official site"}
                                ],
                            }
                        ],
                    }
                ]
            }
        ],
    }

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    assert seen_urls[0].endswith("/v3/serp/google/ai_mode/live/advanced")

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "real"
    assert len(result.aiOverviewComparison) == 1
    assert result.aiOverviewComparison[0].mentioned is True
    assert result.aiOverviewComparison[0].rank == 1
    assert result.aiOverviewComparison[0].platform == "Google AI Mode (DataForSEO Sandbox)"
    # references are not surfaced verbatim in the summary.
    assert "openai.com" not in result.aiOverviewComparison[0].summary


def test_analyze_ai_overview_mode_dataforseo_response_includes_full_summary_and_references(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "type": "ai_overview",
                                "rank_absolute": 1,
                                "markdown": "OpenAI is a well-known AI lab.",
                                "references": [
                                    {"domain": "openai.com", "url": "https://openai.com/about", "title": "About"}
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "urls": ["https://openai.com/pricing"]}
    )
    assert response.status_code == 200

    body = response.json()
    item = body["aiOverviewComparison"][0]
    assert item["fullSummary"] == "OpenAI is a well-known AI lab."
    assert item["references"] == [
        {
            "title": "About",
            "domain": "openai.com",
            "url": "https://openai.com/about",
            "text": None,
            "source": None,
            "position": None,
            "category": "official",
        }
    ]
    assert item["ownDomainReferenced"] is True
    assert item["referenceSummary"] == {
        "total": 1,
        "official": 1,
        "thirdParty": 0,
        "categories": {
            "official": 1,
            "wikipedia": None,
            "sns": None,
            "ugc": None,
            "news": None,
            "media": None,
            "video": None,
            "other": None,
        },
    }

    result = AnalysisResult.model_validate(body)
    assert result.aiOverviewComparison[0].ownDomainReferenced is True


def test_analyze_ai_overview_mode_dataforseo_own_domain_referenced_is_null_without_urls(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "OpenAI."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    # documents (not urls) means there's no "own domain" to compare against.
    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "documents": ["OpenAI builds ChatGPT."]}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["aiOverviewComparison"][0]["ownDomainReferenced"] is None


def test_analyze_mock_ai_overview_response_omits_detail_fields(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    body = response.json()
    for item in body["aiOverviewComparison"]:
        assert item.get("fullSummary") is None
        assert item.get("references") is None
        assert item.get("ownDomainReferenced") is None

    # Existing mock response still validates against the full model.
    AnalysisResult.model_validate(body)


# --- ChatGPT-equivalent observation (services/chatgpt_provider.py) ---------


def _clear_chatgpt_env(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CHATGPT_PROVIDER_MODE",
        "ALLOW_CHATGPT_MODE_OVERRIDE",
        "CHATGPT_MODEL",
        "CHATGPT_MAX_OUTPUT_TOKENS",
        "CHATGPT_REQUEST_LIMIT_PER_ANALYZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_analyze_default_chatgpt_mode_is_off_and_never_calls_openai(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when chatgptMode is off by default")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.chatgptProvider is not None
    assert result.meta.chatgptProvider.mode == "off"
    assert result.meta.chatgptProvider.status == "off"
    assert not any(item.platform.startswith("ChatGPT (") for item in result.aiOverviewComparison)


def test_analyze_chatgpt_mode_openai_adds_a_card_when_ai_overview_mode_is_dataforseo(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")

    dataforseo_payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "OpenAI is great."}]}]}],
    }

    # dataforseo_client and chatgpt_client both `import httpx` and call
    # `httpx.post(...)` directly, so they share the exact same `httpx`
    # module object — monkeypatching `post` on one patches it for both
    # call sites. One dispatching fake_post (by URL) is required instead
    # of two separate monkeypatch.setattr calls, which would just
    # overwrite each other.
    def fake_post(url, **kwargs):
        if url == chatgpt_client.RESPONSES_API_URL:
            return httpx.Response(
                200,
                json={"output_text": "OpenAI is a well-known AI research company."},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(200, json=dataforseo_payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "chatgptMode": "openai"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.chatgptProvider is not None
    assert result.meta.chatgptProvider.mode == "openai"
    assert result.meta.chatgptProvider.status == "real"
    assert result.meta.chatgptProvider.environment == "api"

    platforms = [item.platform for item in result.aiOverviewComparison]
    assert "Google AI Mode (DataForSEO Sandbox)" in platforms
    assert "ChatGPT (OpenAI API)" in platforms

    chatgpt_item = next(item for item in result.aiOverviewComparison if item.platform == "ChatGPT (OpenAI API)")
    assert chatgpt_item.mentioned is True
    assert chatgpt_item.rank is None
    assert chatgpt_item.references is None
    assert chatgpt_item.ownDomainReferenced is None

    # Credentials never leak into the response body.
    body_text = response.text
    assert "sk-super-secret-key" not in body_text
    assert "super-secret-password" not in body_text


def test_analyze_chatgpt_mode_openai_is_skipped_when_ai_overview_mode_is_mock(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called while aiOverviewMode is mock")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "chatgptMode": "openai"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.chatgptProvider is not None
    assert result.meta.chatgptProvider.status == "off"
    # Existing fixed mock aiOverviewComparison (4 items, including its
    # own mock "ChatGPT" card) is unaffected — no second one is added.
    chatgpt_items = [item for item in result.aiOverviewComparison if item.platform == "ChatGPT"]
    assert len(chatgpt_items) == 1
    assert not any(item.platform == "ChatGPT (OpenAI API)" for item in result.aiOverviewComparison)


def test_analyze_chatgpt_mode_request_override_ignored_without_allow_flag(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    # ALLOW_CHATGPT_MODE_OVERRIDE deliberately left unset (false by default).

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without ALLOW_CHATGPT_MODE_OVERRIDE=true")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "chatgptMode": "openai"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.chatgptProvider is not None
    assert result.meta.chatgptProvider.mode == "off"
    assert result.meta.chatgptProvider.status == "off"


def test_analyze_ai_overview_mode_dataforseo_sandbox_failure_does_not_break_analyze(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "unavailable"
    assert result.aiOverviewComparison == []
    # Other real sections must be unaffected.
    assert result.meta.sections.summary == "real"
    assert result.meta.sections.improvements == "real"


def test_analyze_ignores_request_ai_overview_mode_override_by_default(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.delenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", raising=False)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "off"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    # ALLOW_AI_OVERVIEW_MODE_OVERRIDE is unset, so the request's
    # aiOverviewMode must be ignored in favor of the env default.
    assert result.meta.sections.aiOverviewComparison == "mock"
    assert result.meta.aiOverviewProvider.mode == "mock"


def test_analyze_honors_request_ai_overview_mode_override_when_allowed(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "off"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.aiOverviewComparison == "unavailable"
    assert result.aiOverviewComparison == []
    assert result.meta.aiOverviewProvider.mode == "off"


def test_analyze_ai_overview_mode_dataforseo_sandbox_forces_sandbox_even_when_env_is_live(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    # Deliberately "live" — dataforseo_sandbox must ignore this and still
    # call the Sandbox host, with no Live gate check at all.
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.delenv("DATAFORSEO_LIVE_API_ENABLED", raising=False)
    monkeypatch.delenv("DATAFORSEO_LIVE_CONFIRM_TEXT", raising=False)

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "OpenAI is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        assert "sandbox.dataforseo.com" in url
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "dataforseo_sandbox"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.mode == "dataforseo_sandbox"
    assert result.meta.aiOverviewProvider.status == "real"
    assert result.meta.aiOverviewProvider.environment == "sandbox"
    assert result.aiOverviewComparison[0].platform == "Google AI Mode (DataForSEO Sandbox)"


def test_analyze_ai_overview_mode_dataforseo_live_rejected_without_gates_never_calls_httpx(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    # DATAFORSEO_API_ENV left as sandbox (or unset) — dataforseo_live must
    # be rejected because DATAFORSEO_API_ENV isn't "live", regardless of
    # what other gates might be set.
    monkeypatch.delenv("DATAFORSEO_API_ENV", raising=False)
    monkeypatch.delenv("DATAFORSEO_LIVE_API_ENABLED", raising=False)
    monkeypatch.delenv("DATAFORSEO_LIVE_CONFIRM_TEXT", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when dataforseo_live's gates are unmet")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "dataforseo_live"}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.mode == "dataforseo_live"
    assert result.meta.aiOverviewProvider.status == "unavailable"
    assert result.meta.aiOverviewProvider.environment == "unavailable"
    assert result.aiOverviewComparison == []
    assert (
        result.meta.aiOverviewProvider.reason
        == "DataForSEO Live mode was requested, but DATAFORSEO_API_ENV is not live."
    )


def test_analyze_ai_overview_mode_dataforseo_live_succeeds_when_all_gates_are_satisfied(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "ALLOW_DATAFORSEO_LIVE_ONCE")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "OpenAI is great."}]}]}],
    }

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "dataforseo_live"}
    )
    assert response.status_code == 200

    assert seen_urls == ["https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"]

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.mode == "dataforseo_live"
    assert result.meta.aiOverviewProvider.status == "real"
    assert result.meta.aiOverviewProvider.environment == "live"
    assert result.aiOverviewComparison[0].platform == "Google AI Mode (DataForSEO Live)"
    # Credentials never leak into the response body.
    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "someone@example.com" not in raw_body


def test_analyze_chatgpt_openai_combines_with_dataforseo_sandbox_mode(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")

    dataforseo_payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "OpenAI is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        if url == chatgpt_client.RESPONSES_API_URL:
            return httpx.Response(
                200,
                json={"output_text": "OpenAI is a well-known AI research company."},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(200, json=dataforseo_payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "aiOverviewMode": "dataforseo_sandbox", "chatgptMode": "openai"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.mode == "dataforseo_sandbox"
    assert result.meta.chatgptProvider.status == "real"

    platforms = [item.platform for item in result.aiOverviewComparison]
    assert "Google AI Mode (DataForSEO Sandbox)" in platforms
    assert "ChatGPT (OpenAI API)" in platforms


def test_analyze_chatgpt_openai_combines_with_dataforseo_live_mode(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "ALLOW_DATAFORSEO_LIVE_ONCE")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")

    dataforseo_payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "OpenAI is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        if url == chatgpt_client.RESPONSES_API_URL:
            return httpx.Response(
                200,
                json={"output_text": "OpenAI is a well-known AI research company."},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(200, json=dataforseo_payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "aiOverviewMode": "dataforseo_live", "chatgptMode": "openai"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.aiOverviewProvider.mode == "dataforseo_live"
    assert result.meta.aiOverviewProvider.environment == "live"
    assert result.meta.chatgptProvider.status == "real"

    platforms = [item.platform for item in result.aiOverviewComparison]
    assert "Google AI Mode (DataForSEO Live)" in platforms
    assert "ChatGPT (OpenAI API)" in platforms

    # Credentials never leak into the response body.
    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "sk-super-secret-key" not in raw_body


def test_analyze_rejects_invalid_ai_overview_mode_value():
    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "aiOverviewMode": "real"}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


def test_analyze_normalizes_fullwidth_user_provided_documents_before_cooccurrence():
    # The document below only mentions the brand in full-width form
    # ("ＯｐｅｎＡＩ"). Without the Normalizer stage folding it to
    # half-width ("OpenAI") before the brand-name window search, this
    # document would never match brandName at all and the ranking
    # would come back empty.
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": ["ＯｐｅｎＡＩの料金プランについて教えてください。"],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    keywords = {kw.keyword for kw in result.cooccurrenceRanking}
    assert "料金" in keywords


def test_analyze_uses_sample_documents_when_documents_and_urls_omitted():
    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentsSource == "development_sample"
    # The built-in sample documents mention 料金/プラン/導入/事例 etc.
    # around the brand name, so the ranking should not be empty.
    assert len(result.cooccurrenceRanking) > 0
    # development_sample documents are wrapped as Document[] too (see
    # docs/11_architecture_v1.md), so documentCount/sourceTypes are
    # populated just like the other two sources.
    assert result.meta.documentCount == len(SAMPLE_DOCUMENT_TEMPLATES)
    assert result.meta.sourceTypes == ["development_sample"]
    # Each sample document is short, so the Chunker produces exactly
    # one chunk per document (see services/document_chunker.py).
    assert result.meta.chunkCount == len(SAMPLE_DOCUMENT_TEMPLATES)


def test_analyze_reports_document_count_and_source_types_for_user_provided_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": [
                "OpenAIの料金プランについて教えてください。",
                "OpenAIの料金プランはとても安いです。",
            ],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentCount == 2
    assert result.meta.sourceTypes == ["user_provided"]
    assert result.meta.chunkCount == 2


def test_analyze_reports_a_higher_chunk_count_for_a_long_document():
    long_document = "OpenAIの料金プランについて教えてください。" + "あ" * 3000

    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "documents": [long_document]},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentCount == 1
    # One long Document should split into multiple chunks, unlike the
    # 1-chunk-per-short-document cases above.
    assert result.meta.chunkCount is not None
    assert result.meta.chunkCount > 1


def test_analyze_accepts_empty_documents_list():
    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "documents": []}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.cooccurrenceRanking == []
    assert result.meta.documentsSource == "user_provided"
    # The Document pipeline still ran and reports 0 documents — this is
    # a valid "analyze zero documents" request, not a skipped pipeline.
    assert result.meta.documentCount == 0
    assert result.meta.sourceTypes == []
    # contextAnalysis/summary mirror cooccurrenceRanking's status:
    # "real" with zero chunks/documents to analyze, same "computed over
    # zero input" semantics.
    assert result.meta.sections.contextAnalysis == "real"
    assert result.contextAnalysis == []
    assert result.meta.sections.summary == "real"
    assert result.summary.totalMentions == 0
    assert result.summary.sentimentBreakdown.neutral == 100
    # improvements mirrors the same status too: 0 documents is a valid
    # "analyzed zero input" state, so build_improvement_suggestions()
    # still runs and returns its fallback suggestion rather than [].
    assert result.meta.sections.improvements == "real"
    assert len(result.improvements) > 0


def test_analyze_documents_take_priority_over_urls():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": ["OpenAIの料金プランについて教えてください。"],
            "urls": ["http://localhost/should-be-ignored"],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentsSource == "user_provided"
    assert result.meta.urlFetchResults is None
    keywords = {kw.keyword for kw in result.cooccurrenceRanking}
    assert "料金" in keywords


def test_analyze_urls_with_disallowed_host_report_failure_but_still_return_200():
    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "urls": ["http://localhost/x"]},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentsSource == "web_fetch"
    assert result.meta.urlFetchResults is not None
    assert result.meta.urlFetchResults[0].success is False
    # No successful fetch -> nothing to analyze. This is not a request
    # error, but cooccurrenceRanking is "unavailable" (not "real"),
    # since it couldn't be computed at all rather than legitimately
    # computing zero results.
    assert result.cooccurrenceRanking == []
    assert result.meta.sections.cooccurrenceRanking == "unavailable"
    assert result.contextAnalysis == []
    assert result.meta.sections.contextAnalysis == "unavailable"
    assert result.meta.sections.summary == "unavailable"
    assert result.summary.totalMentions == 0
    # Every url failed -> nothing to base suggestions on, so
    # improvements is "unavailable" and [] rather than a fallback
    # suggestion (that fallback is only for a legitimate zero-input
    # analysis, e.g. documents: []).
    assert result.meta.sections.improvements == "unavailable"
    assert result.improvements == []


def test_analyze_rejects_empty_urls_list():
    response = client.post("/analyze", json={"brandName": "OpenAI", "urls": []})
    assert response.status_code == 400
    assert response.json() == {"error": "urls must not be empty"}


def test_analyze_urls_all_succeed_reports_real_status(monkeypatch):
    def fake_fetch(urls):
        return [
            FetcherResult(url=u, success=True, text="OpenAIの料金プランについて説明する文章です。")
            for u in urls
        ]

    monkeypatch.setattr(main, "fetch_url_texts", fake_fetch)

    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "urls": ["https://example.com/a", "https://example.com/b"],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.documentsSource == "web_fetch"
    assert result.meta.urlFetchResults is not None
    assert all(r.success for r in result.meta.urlFetchResults)
    assert len(result.cooccurrenceRanking) > 0
    # Both URLs succeeded -> both became Documents.
    assert result.meta.documentCount == 2
    assert result.meta.sourceTypes == ["web_fetch"]
    assert result.meta.sections.contextAnalysis == "real"
    assert len(result.contextAnalysis) > 0
    assert result.meta.sections.summary == "real"
    assert result.summary.totalMentions > 0
    assert result.meta.sections.improvements == "real"
    assert len(result.improvements) > 0


def test_analyze_urls_partial_failure_reports_real_status_and_both_results(monkeypatch):
    def fake_fetch(urls):
        return [
            FetcherResult(
                url=urls[0], success=True, text="OpenAIの料金プランについて説明する文章です。"
            ),
            FetcherResult(url=urls[1], success=False, error="timeout"),
        ]

    monkeypatch.setattr(main, "fetch_url_texts", fake_fetch)

    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "urls": ["https://example.com/a", "https://example.com/b"],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    # At least one URL succeeded, so this is a "real" (if partial) result.
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.urlFetchResults is not None
    successes = [r for r in result.meta.urlFetchResults if r.success]
    failures = [r for r in result.meta.urlFetchResults if not r.success]
    assert len(successes) == 1
    assert len(failures) == 1
    # Only the successful fetch became a Document — the failed one is
    # not "Document-ified" (it's already tracked via urlFetchResults).
    assert result.meta.documentCount == 1
    assert result.meta.sourceTypes == ["web_fetch"]


def test_analyze_urls_all_fail_reports_unavailable_status(monkeypatch):
    def fake_fetch(urls):
        return [FetcherResult(url=u, success=False, error="boom") for u in urls]

    monkeypatch.setattr(main, "fetch_url_texts", fake_fetch)

    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "urls": ["https://example.com/a", "https://example.com/b"],
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.sections.cooccurrenceRanking == "unavailable"
    assert result.cooccurrenceRanking == []
    assert result.meta.urlFetchResults is not None
    assert all(not r.success for r in result.meta.urlFetchResults)
    # No successful fetch -> the Document pipeline ran but found
    # nothing to wrap (0 documents, not omitted).
    assert result.meta.documentCount == 0
    assert result.meta.sourceTypes == []
    assert result.meta.sections.contextAnalysis == "unavailable"
    assert result.contextAnalysis == []
    assert result.meta.sections.summary == "unavailable"
    assert result.meta.sections.improvements == "unavailable"
    assert result.improvements == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"brandName": ""},
        {"brandName": "   "},
    ],
)
def test_analyze_rejects_empty_brand_name(payload):
    response = client.post("/analyze", json=payload)
    assert response.status_code == 400
    assert response.json() == {"error": "brandName is required"}


def test_analyze_rejects_brand_name_over_max_length():
    response = client.post("/analyze", json={"brandName": "a" * 201})
    assert response.status_code == 400
    assert response.json() == {
        "error": "brandName must be 200 characters or fewer"
    }


def test_analyze_accepts_brand_name_at_max_length():
    response = client.post("/analyze", json={"brandName": "a" * 200})
    assert response.status_code == 200


def test_analyze_rejects_malformed_body():
    response = client.post("/analyze", json={"brandName": 123})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


def test_analyze_rejects_too_many_documents():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "documents": ["OpenAIについて。"] * (MAX_DOCUMENTS_COUNT + 1),
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": f"documents must contain {MAX_DOCUMENTS_COUNT} or fewer entries"
    }


def test_analyze_rejects_document_over_max_length():
    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "documents": ["a" * (MAX_DOCUMENT_LENGTH + 1)]},
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": f"each document must be {MAX_DOCUMENT_LENGTH} characters or fewer"
    }


def test_analyze_rejects_documents_over_total_length():
    # Each document is within the per-document limit, but there are
    # enough of them that the total exceeds MAX_TOTAL_DOCUMENTS_LENGTH.
    doc = "a" * MAX_DOCUMENT_LENGTH
    count = (MAX_TOTAL_DOCUMENTS_LENGTH // MAX_DOCUMENT_LENGTH) + 1
    response = client.post(
        "/analyze",
        json={"brandName": "OpenAI", "documents": [doc] * count},
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": f"documents must total {MAX_TOTAL_DOCUMENTS_LENGTH} characters or fewer"
    }


def test_analyze_rejects_too_many_urls():
    response = client.post(
        "/analyze",
        json={
            "brandName": "OpenAI",
            "urls": [f"https://example.com/{i}" for i in range(MAX_URLS + 1)],
        },
    )
    assert response.status_code == 400
    assert response.json() == {"error": f"urls must contain {MAX_URLS} or fewer entries"}


# --- Common Crawl /analyze integration --------------------------------------


def _clear_common_crawl_env(monkeypatch):
    for name in (
        "COMMON_CRAWL_ENABLED",
        "COMMON_CRAWL_INDEX",
        "COMMON_CRAWL_MAX_RESULTS",
        "COMMON_CRAWL_TIMEOUT_SECONDS",
        "COMMON_CRAWL_USER_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)


def _enable_common_crawl(monkeypatch, index="CC-MAIN-2026-08"):
    """Sets a fixed `index` (not "latest") so tests never need to mock
    a collinfo.json request in addition to the Index API/WARC ones.
    """
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_ENABLED", "true")
    monkeypatch.setenv("COMMON_CRAWL_INDEX", index)


_CC_CANDIDATE_FILENAME = "crawl-data/CC-MAIN-2026-08/segments/x/warc/foo.warc.gz"


def _cdxj_line(url="https://cybozu.co.jp/about", **overrides) -> str:
    fields = {
        "url": url,
        "timestamp": "20260101000000",
        "status": 200,
        "mime": "text/html",
        "digest": "abc123",
        "filename": _CC_CANDIDATE_FILENAME,
        "offset": 1000,
        "length": 2000,
    }
    fields.update(overrides)
    return json.dumps(fields)


def _gzipped_warc_html(html: bytes = b"<html><body>Cybozu is great.</body></html>") -> bytes:
    record = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        b"\r\n"
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=UTF-8\r\n"
        b"\r\n" + html
    )
    return gzip.compress(record)


def _fake_common_crawl_get_success(url, **kwargs):
    if url.endswith("-index"):
        return httpx.Response(200, text=_cdxj_line(), request=httpx.Request("GET", url))
    return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))


def test_analyze_common_crawl_mode_unspecified_defaults_to_off(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Common Crawl should not be called when commonCrawlMode is unspecified")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    response = client.post("/analyze", json={"brandName": "Cybozu"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider is not None
    assert result.meta.commonCrawlProvider.mode == "off"
    assert result.meta.commonCrawlProvider.status == "off"


def test_analyze_common_crawl_mode_off_never_calls_service(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Common Crawl should not be called when commonCrawlMode is off")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "off", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.mode == "off"
    assert result.meta.commonCrawlProvider.status == "off"


def test_analyze_rejects_invalid_common_crawl_mode_value():
    response = client.post(
        "/analyze", json={"brandName": "Cybozu", "commonCrawlMode": "brand_name"}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


def test_analyze_common_crawl_enabled_false_never_calls_service_even_with_domain_mode(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_ENABLED", "false")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Common Crawl should not be called when COMMON_CRAWL_ENABLED is false")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.mode == "domain"
    assert result.meta.commonCrawlProvider.status == "off"


def test_analyze_common_crawl_domain_mode_searches_fetches_and_adds_a_document(monkeypatch):
    _enable_common_crawl(monkeypatch)
    monkeypatch.setattr(common_crawl_index.httpx, "get", _fake_common_crawl_get_success)

    response = client.post(
        "/analyze",
        json={
            "brandName": "Cybozu",
            "commonCrawlMode": "domain",
            "commonCrawlDomain": "cybozu.co.jp",
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.mode == "domain"
    assert provider.status == "real"
    assert provider.domain == "cybozu.co.jp"
    assert provider.crawlIndex == "CC-MAIN-2026-08"
    assert provider.candidateCount == 1
    assert provider.documentCount == 1
    assert "common_crawl" in (result.meta.sourceTypes or [])
    # summary.topPlatforms must reflect the Common Crawl document that
    # was actually added, and must not say it's unimplemented.
    assert "Common Crawl補完" in result.summary.topPlatforms
    assert not any("未実装" in label for label in result.summary.topPlatforms)


def test_analyze_common_crawl_domain_falls_back_to_urls_hostname(monkeypatch):
    _enable_common_crawl(monkeypatch)

    captured_search_urls = []

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            captured_search_urls.append(kwargs.get("params"))
            return httpx.Response(200, text=_cdxj_line(), request=httpx.Request("GET", url))
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={
            "brandName": "Cybozu",
            "urls": ["https://cybozu.co.jp/about"],
            "commonCrawlMode": "domain",
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.domain == "cybozu.co.jp"
    assert result.meta.commonCrawlProvider.status == "real"
    params = dict(captured_search_urls[0])
    assert params["url"] == "cybozu.co.jp/*"


def test_analyze_common_crawl_domain_undeterminable_is_unavailable(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Common Crawl should not be called when no domain can be determined")

    monkeypatch.setattr(common_crawl_index.httpx, "get", fail_if_called)

    response = client.post("/analyze", json={"brandName": "Cybozu", "commonCrawlMode": "domain"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "unavailable"
    assert result.meta.commonCrawlProvider.domain is None


def test_analyze_succeeds_when_common_crawl_index_search_finds_zero_results(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "unavailable"
    assert result.meta.commonCrawlProvider.documentCount == 0
    assert result.cooccurrenceRanking is not None


def test_analyze_succeeds_when_common_crawl_warc_fetch_fails(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_line(), request=httpx.Request("GET", url))
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "unavailable"
    assert result.meta.commonCrawlProvider.candidateCount == 1
    assert result.meta.commonCrawlProvider.documentCount == 0


def test_analyze_succeeds_when_common_crawl_document_conversion_fails(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_line(), request=httpx.Request("GET", url))
        # Non-HTML content type -> build_common_crawl_document() reports unavailable.
        return httpx.Response(
            200,
            content=gzip.compress(
                b"WARC/1.0\r\nWARC-Type: response\r\n\r\n"
                b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n\x89PNG"
            ),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "unavailable"
    assert result.meta.commonCrawlProvider.documentCount == 0


def test_analyze_common_crawl_provider_reason_never_contains_a_huge_response_body(monkeypatch):
    # A successfully-added Common Crawl document's *text* legitimately
    # appears in the analysis output (contextAnalysis/summary quotes) —
    # that's the point of adding it. What must never happen is the raw
    # WARC/HTML payload leaking into meta.commonCrawlProvider itself
    # (which has no field for it at all — only status/reason/domain/
    # crawlIndex/candidateCount/documentCount), so this exercises a
    # failure path with a deliberately huge garbage WARC response and
    # checks the resulting `reason` stays short.
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_line(), request=httpx.Request("GET", url))
        return httpx.Response(200, content=b"not gzip " * 100_000, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "unavailable"
    assert len(result.meta.commonCrawlProvider.reason) < 500


def test_analyze_common_crawl_combines_with_dataforseo_and_chatgpt(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "dataforseo")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")

    _enable_common_crawl(monkeypatch)
    monkeypatch.setattr(common_crawl_index.httpx, "get", _fake_common_crawl_get_success)

    dataforseo_payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "Cybozu is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        if url == chatgpt_client.RESPONSES_API_URL:
            return httpx.Response(
                200,
                json={"output_text": "Cybozu is a well-known teamwork software company."},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(200, json=dataforseo_payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    response = client.post(
        "/analyze",
        json={
            "brandName": "Cybozu",
            "commonCrawlMode": "domain",
            "commonCrawlDomain": "cybozu.co.jp",
            "chatgptMode": "openai",
        },
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.commonCrawlProvider.status == "real"
    assert result.meta.aiOverviewProvider.mode == "dataforseo"
    assert result.meta.chatgptProvider.status == "real"

    # Credentials never leak into the response body.
    raw_body = response.text
    assert "super-secret-password" not in raw_body
    assert "sk-super-secret-key" not in raw_body


# --- Common Crawl multi-document /analyze integration -----------------------
# Added 2026-07-28 (feature/common-crawl-multiple-documents): the flow above
# added at most one Common Crawl Document per /analyze call; this extends it
# to up to main.COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE (3), trying up to
# main.COMMON_CRAWL_MAX_CANDIDATES_TO_TRY (5) candidates in order and
# skipping any that fail to fetch/convert. See docs/13_common_crawl_mvp_design.md.


def _cdxj_multi_lines(count: int) -> str:
    """`count` distinct candidates, each with its own URL and WARC
    `filename` so a test's fake WARC-fetch handler can tell them apart
    by request URL (see `_warc_fetch_index_from_url` below).
    """
    return "\n".join(
        _cdxj_line(
            url=f"https://cybozu.co.jp/page{i}",
            filename=f"crawl-data/CC-MAIN-2026-08/segments/x/warc/foo{i}.warc.gz",
        )
        for i in range(count)
    )


def _warc_fetch_index_from_url(url: str) -> int:
    # WARC fetch requests hit f"{COMMON_CRAWL_WARC_HOST}/{filename}" (see
    # services/common_crawl_warc.py) where filename ends in "fooN.warc.gz".
    match = re.search(r"foo(\d+)\.warc\.gz$", url)
    assert match is not None, url
    return int(match.group(1))


def test_analyze_common_crawl_caps_at_max_documents_even_with_more_successful_candidates(monkeypatch):
    _enable_common_crawl(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "5")

    fetch_calls = []

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(5), request=httpx.Request("GET", url))
        fetch_calls.append(url)
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "real"
    assert provider.candidateCount == 5
    assert provider.documentCount == 3
    # Only the first 3 candidates should ever be fetched — the 4th/5th
    # successful candidates are never even tried once the cap is hit.
    assert len(fetch_calls) == 3
    assert "partial" not in provider.reason.lower()


def test_analyze_common_crawl_tries_at_most_five_candidates(monkeypatch):
    _enable_common_crawl(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "8")

    fetch_calls = []

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(8), request=httpx.Request("GET", url))
        fetch_calls.append(url)
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "unavailable"
    assert provider.candidateCount == 8
    assert provider.documentCount == 0
    # Index reported 8 candidates, but at most 5 are ever tried.
    assert len(fetch_calls) == 5


def test_analyze_common_crawl_skips_candidate_when_warc_fetch_fails(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(2), request=httpx.Request("GET", url))
        if _warc_fetch_index_from_url(url) == 0:
            return httpx.Response(500, request=httpx.Request("GET", url))
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "real"
    assert provider.candidateCount == 2
    assert provider.documentCount == 1


def test_analyze_common_crawl_skips_candidate_when_document_conversion_fails(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(2), request=httpx.Request("GET", url))
        if _warc_fetch_index_from_url(url) == 0:
            # Non-HTML content type -> build_common_crawl_document() reports unavailable.
            return httpx.Response(
                200,
                content=gzip.compress(
                    b"WARC/1.0\r\nWARC-Type: response\r\n\r\n"
                    b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n\x89PNG"
                ),
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "real"
    assert provider.documentCount == 1


def test_analyze_common_crawl_partial_success_reports_partial_reason_and_analyze_succeeds(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(2), request=httpx.Request("GET", url))
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "real"
    assert provider.candidateCount == 2
    assert provider.documentCount == 2
    assert "partial" in provider.reason.lower()
    assert result.cooccurrenceRanking is not None


def test_analyze_succeeds_when_all_common_crawl_candidates_fail_to_fetch(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(5), request=httpx.Request("GET", url))
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.status == "unavailable"
    assert provider.candidateCount == 5
    assert provider.documentCount == 0
    assert result.cooccurrenceRanking is not None


def test_analyze_common_crawl_multi_document_reason_never_contains_html_or_warc_body(monkeypatch):
    _enable_common_crawl(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("-index"):
            return httpx.Response(200, text=_cdxj_multi_lines(3), request=httpx.Request("GET", url))
        return httpx.Response(200, content=_gzipped_warc_html(), request=httpx.Request("GET", url))

    monkeypatch.setattr(common_crawl_index.httpx, "get", fake_get)

    response = client.post(
        "/analyze",
        json={"brandName": "Cybozu", "commonCrawlMode": "domain", "commonCrawlDomain": "cybozu.co.jp"},
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    provider = result.meta.commonCrawlProvider
    assert provider.documentCount == 3
    assert "<html" not in provider.reason
    assert "WARC/1.0" not in provider.reason
    raw_body = response.text
    assert "WARC/1.0" not in raw_body
