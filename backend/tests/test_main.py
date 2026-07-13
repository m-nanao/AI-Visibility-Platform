import pytest
from fastapi.testclient import TestClient

from main import app
from models import (
    MAX_DOCUMENT_LENGTH,
    MAX_DOCUMENTS_COUNT,
    MAX_TOTAL_DOCUMENTS_LENGTH,
    MAX_URLS,
    AnalysisResult,
)

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_analyze_accepts_empty_documents_list():
    response = client.post(
        "/analyze", json={"brandName": "OpenAI", "documents": []}
    )
    assert response.status_code == 200

    result = AnalysisResult.model_validate(response.json())
    assert result.cooccurrenceRanking == []
    assert result.meta.documentsSource == "user_provided"


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
    # No successful fetch -> nothing to analyze, but this is not an error.
    assert result.cooccurrenceRanking == []


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
