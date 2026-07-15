import subprocess
import sys
from pathlib import Path

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
    # cooccurrenceRanking is always genuinely computed (from
    # caller-supplied documents/urls, or development sample documents),
    # but the other sections are still fixed placeholder data.
    assert result.meta.sections.cooccurrenceRanking == "real"
    assert result.meta.sections.summary == "mock"
    assert result.meta.sections.contextAnalysis == "mock"
    assert result.meta.sections.aiOverviewComparison == "mock"
    assert result.meta.sections.improvements == "mock"
    assert result.meta.documentsSource == "development_sample"


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


def test_analyze_uses_sample_documents_when_documents_and_urls_omitted():
    response = client.post("/analyze", json={"brandName": "OpenAI"})
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.meta.documentsSource == "development_sample"
    # The built-in sample documents mention 料金/プラン/導入/事例 etc.
    # around the brand name, so the ranking should not be empty.
    assert len(result.cooccurrenceRanking) > 0
    # development_sample documents aren't wrapped as Document[] yet
    # (see docs/11_architecture_v1.md), so there's no summary to report.
    assert result.meta.documentCount is None
    assert result.meta.sourceTypes is None


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


def test_analyze_accepts_empty_documents_list():
    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "documents": []}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.cooccurrenceRanking == []
    assert result.meta.documentsSource == "user_provided"
    # The Document pipeline still ran (documentCount is 0, not None) —
    # distinguishes "ran with zero documents" from "didn't run at all"
    # (development_sample, see the test above).
    assert result.meta.documentCount == 0
    assert result.meta.sourceTypes == []


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
    # nothing to wrap (0, not None — it did run, unlike development_sample).
    assert result.meta.documentCount == 0
    assert result.meta.sourceTypes == []


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
