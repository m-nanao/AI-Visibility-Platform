"""Task 6-D-4C-2 (feature/gemini-external-document-supplement):
backward compatibility for AIOverviewComparisonItem's new
geminiExternalDocumentSources/geminiExternalDocumentSourcesConsideredCount
fields, for AnalysisMeta's new geminiExternalDocumentProvider field,
and for ObservationMethod's new "external_document_supplement" value
— saved history from before this task existed must still parse
successfully, with every new field defaulting to None. Mirrors
tests/test_gemini_websearch_grounding_backward_compat.py's structure.
"""

from models import (
    AIOverviewComparisonItem,
    AnalysisMeta,
    GeminiExternalDocumentSource,
)


def test_old_gemini_card_without_any_of_the_new_fields_still_parses():
    old_item = {
        "platform": "Gemini (Google API)",
        "mentioned": True,
        "rank": None,
        "summary": "Acme is a company.",
    }

    item = AIOverviewComparisonItem.model_validate(old_item)

    assert item.observationMethod is None
    assert item.geminiExternalDocumentSources is None
    assert item.geminiExternalDocumentSourcesConsideredCount is None


def test_new_external_document_fields_round_trip_when_present():
    item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API, 外部文書補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "external_document_supplement",
            "model": "gemini-2.5-flash",
            "geminiExternalDocumentSources": [
                {
                    "sourceUrl": "https://acme.example.com",
                    "title": "Acme",
                    "domain": "acme.example.com",
                    "originalIndex": 0,
                    "inputOrder": 0,
                    "inputCharCount": 123,
                    "truncated": False,
                }
            ],
            "geminiExternalDocumentSourcesConsideredCount": 1,
        }
    )

    assert item.observationMethod == "external_document_supplement"
    assert item.model == "gemini-2.5-flash"
    assert item.geminiExternalDocumentSources == [
        GeminiExternalDocumentSource(
            sourceUrl="https://acme.example.com",
            title="Acme",
            domain="acme.example.com",
            originalIndex=0,
            inputOrder=0,
            inputCharCount=123,
            truncated=False,
        )
    ]
    assert item.geminiExternalDocumentSourcesConsideredCount == 1


def test_old_analysis_meta_without_gemini_external_document_provider_still_parses():
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
    assert meta.geminiExternalDocumentProvider is None


def test_external_document_supplement_observation_method_is_distinct_from_websearch_supplement():
    """The new ObservationMethod value must never be confused with the
    existing "websearch_supplement" value — the two cards mean
    categorically different things (see models.ObservationMethod's
    own docstring)."""
    websearch_item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API, Web検索補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "websearch_supplement",
        }
    )
    external_document_item = AIOverviewComparisonItem.model_validate(
        {
            "platform": "Gemini (Google API, 外部文書補完)",
            "mentioned": True,
            "rank": None,
            "summary": "Acme is a company.",
            "observationMethod": "external_document_supplement",
        }
    )

    assert websearch_item.observationMethod != external_document_item.observationMethod
