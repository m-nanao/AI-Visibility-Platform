"""Task 6-D-3D follow-up (feature/chatgpt-full-text-citations):
backward compatibility for AIOverviewComparisonItem's new
citationAnnotations/citationAnnotationsTotalCount/citationsTruncated/
fullSummaryTruncated fields — saved history from before this task
existed must still parse successfully, with all four new fields
defaulting to None/falsy.
"""

from models import AIOverviewComparisonItem, WebsearchCitationAnnotation


def test_old_websearch_card_without_any_of_the_new_fields_still_parses():
    old_item = {
        "platform": "ChatGPT (OpenAI API, Web検索補完)",
        "mentioned": True,
        "rank": None,
        "summary": "Acme is a company.",
        "fullSummary": "Acme is a company. " * 5,
        "references": [{"url": "https://acme.example.com", "title": "Acme"}],
        "observationMethod": "websearch_supplement",
    }

    item = AIOverviewComparisonItem.model_validate(old_item)

    assert item.fullSummaryTruncated is None
    assert item.citationAnnotations is None
    assert item.citationAnnotationsTotalCount is None
    assert item.citationsTruncated is None


def test_old_no_search_card_without_any_of_the_new_fields_still_parses():
    old_item = {
        "platform": "ChatGPT (OpenAI API)",
        "mentioned": True,
        "rank": None,
        "summary": "Acme is a company.",
    }

    item = AIOverviewComparisonItem.model_validate(old_item)

    assert item.fullSummaryTruncated is None
    assert item.citationAnnotations is None
    assert item.citationAnnotationsTotalCount is None
    assert item.citationsTruncated is None


def test_new_fields_round_trip_when_present():
    item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "ChatGPT (OpenAI API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "fullSummaryTruncated": False,
            "citationAnnotations": [
                {
                    "url": "https://acme.example.com?utm_source=openai",
                    "title": "Acme",
                    "startIndex": 10,
                    "endIndex": 20,
                }
            ],
            "citationAnnotationsTotalCount": 1,
            "citationsTruncated": False,
        }
    )

    assert item.fullSummaryTruncated is False
    assert item.citationAnnotations == [
        WebsearchCitationAnnotation(
            url="https://acme.example.com?utm_source=openai",
            title="Acme",
            startIndex=10,
            endIndex=20,
        )
    ]
    assert item.citationAnnotationsTotalCount == 1
    assert item.citationsTruncated is False
