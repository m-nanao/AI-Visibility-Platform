import pytest
from fastapi.testclient import TestClient

from main import app
from models import AnalysisResult

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
    assert result.meta.source == "python_mock"
    assert result.meta.isMock is True


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
