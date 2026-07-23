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
from services import dataforseo_client
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
