"""Task 6-D-4B-2 (feature/gemini-websearch-supplement): backward
compatibility for AIOverviewComparisonItem's new
geminiGroundingChunks/geminiGroundingChunksTotalCount/
geminiGroundingSupports/geminiGroundingSupportsTotalCount/
geminiSearchEntryPointRenderedContent/
geminiSearchEntryPointRenderedContentTruncated fields, and for
AnalysisMeta's new geminiWebsearchProvider field — saved history from
before this task existed must still parse successfully, with every
new field defaulting to None. Mirrors
tests/test_claude_websearch_citation_backward_compat.py's structure.
"""

from models import (
    AIOverviewComparisonItem,
    AnalysisMeta,
    GeminiWebsearchGroundingChunk,
    GeminiWebsearchGroundingSupport,
)


def test_old_gemini_card_without_any_of_the_new_fields_still_parses():
    old_item = {
        "platform": "Gemini (Google API)",
        "mentioned": True,
        "rank": None,
        "summary": "Acme is a company.",
    }

    item = AIOverviewComparisonItem.model_validate(old_item)

    assert item.geminiGroundingChunks is None
    assert item.geminiGroundingChunksTotalCount is None
    assert item.geminiGroundingSupports is None
    assert item.geminiGroundingSupportsTotalCount is None
    assert item.geminiSearchEntryPointRenderedContent is None
    assert item.geminiSearchEntryPointRenderedContentTruncated is None
    assert item.citationsTruncated is None
    assert item.model is None


def test_new_gemini_websearch_fields_round_trip_when_present():
    item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "websearch_supplement",
            "model": "gemini-2.5-flash",
            "geminiGroundingChunks": [
                {"uri": "https://acme.example.com", "title": "Acme", "domain": "acme.example.com"}
            ],
            "geminiGroundingChunksTotalCount": 1,
            "geminiGroundingSupports": [
                {
                    "startIndex": 0,
                    "endIndex": 10,
                    "text": "Acme makes",
                    "groundingChunkIndices": [0],
                    "confidenceScores": [0.9],
                }
            ],
            "geminiGroundingSupportsTotalCount": 1,
            "geminiSearchEntryPointRenderedContent": "<div>...</div>",
            "geminiSearchEntryPointRenderedContentTruncated": False,
            "citationsTruncated": False,
        }
    )

    assert item.model == "gemini-2.5-flash"
    assert item.geminiGroundingChunks == [
        GeminiWebsearchGroundingChunk(
            uri="https://acme.example.com", title="Acme", domain="acme.example.com"
        )
    ]
    assert item.geminiGroundingChunksTotalCount == 1
    assert item.geminiGroundingSupports == [
        GeminiWebsearchGroundingSupport(
            startIndex=0,
            endIndex=10,
            text="Acme makes",
            groundingChunkIndices=[0],
            confidenceScores=[0.9],
        )
    ]
    assert item.geminiGroundingSupportsTotalCount == 1
    assert item.geminiSearchEntryPointRenderedContent == "<div>...</div>"
    assert item.geminiSearchEntryPointRenderedContentTruncated is False
    assert item.citationsTruncated is False


def test_old_analysis_meta_without_gemini_websearch_provider_still_parses():
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
    assert meta.geminiWebsearchProvider is None


def test_no_search_and_websearch_cards_can_carry_different_models():
    """Mirrors Claude's equivalent test — Gemini's no-search card (no
    `model` field populated yet by services/gemini_provider.py, a
    known pre-existing gap this task does not fix) and its
    websearch-supplement card are still independent fields on two
    separate AIOverviewComparisonItem instances."""
    no_search = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
        }
    )
    websearch = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "websearch_supplement",
            "model": "gemini-2.5-flash",
        }
    )

    assert no_search.model is None
    assert websearch.model == "gemini-2.5-flash"
