"""Task 6-D-4A-2 (feature/claude-websearch-supplement): backward
compatibility for AIOverviewComparisonItem's new
claudeCitationAnnotations/claudeCitationAnnotationsTotalCount fields,
and for AnalysisMeta's new claudeWebsearchProvider field — saved
history from before this task existed must still parse successfully,
with every new field defaulting to None. Mirrors
tests/test_chatgpt_websearch_citation_backward_compat.py's structure.
"""

from models import (
    AIOverviewComparisonItem,
    AnalysisMeta,
    ClaudeWebsearchCitationAnnotation,
)


def test_old_claude_card_without_any_of_the_new_fields_still_parses():
    old_item = {
        "platform": "Claude (Anthropic API)",
        "mentioned": True,
        "rank": None,
        "summary": "Acme is a company.",
    }

    item = AIOverviewComparisonItem.model_validate(old_item)

    assert item.claudeCitationAnnotations is None
    assert item.claudeCitationAnnotationsTotalCount is None
    assert item.citationsTruncated is None
    assert item.model is None


def test_no_search_and_websearch_cards_can_carry_different_models():
    """Task 6-D-4A-2 final review item 1: the no-search card's model
    and the websearch-supplement card's model are independent fields
    on two separate AIOverviewComparisonItem instances — one provider
    can legitimately report two different model ids for the same
    brand in the same saved history row."""
    no_search = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Claude (Anthropic API)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "model": "claude-sonnet-4-5",
        }
    )
    websearch = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Claude (Anthropic API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "websearch_supplement",
            "model": "claude-sonnet-5-5",
        }
    )

    assert no_search.model == "claude-sonnet-4-5"
    assert websearch.model == "claude-sonnet-5-5"
    assert no_search.model != websearch.model


def test_new_claude_websearch_fields_round_trip_when_present():
    item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Claude (Anthropic API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "websearch_supplement",
            "claudeCitationAnnotations": [
                {
                    "url": "https://acme.example.com?utm_source=anthropic",
                    "title": "Acme",
                    "citedText": "Acme makes widgets",
                }
            ],
            "claudeCitationAnnotationsTotalCount": 1,
            "citationsTruncated": False,
        }
    )

    assert item.claudeCitationAnnotations == [
        ClaudeWebsearchCitationAnnotation(
            url="https://acme.example.com?utm_source=anthropic",
            title="Acme",
            citedText="Acme makes widgets",
        )
    ]
    assert item.claudeCitationAnnotationsTotalCount == 1
    assert item.citationsTruncated is False


def test_old_analysis_meta_without_claude_websearch_provider_still_parses():
    # Minimal shape matching a pre-Task-6-D-4A-2 saved history row's
    # meta — claudeWebsearchProvider key absent entirely.
    old_meta = {
        "sections": {
            "summary": "mock",
            "cooccurrenceRanking": "mock",
            "contextAnalysis": "mock",
            "aiOverviewComparison": "mock",
            "improvements": "mock",
        },
        "documentsSource": "development_sample",
        "generatedAt": "2026-01-01T00:00:00Z",
    }
    meta = AnalysisMeta.model_validate(old_meta)
    assert meta.claudeWebsearchProvider is None
