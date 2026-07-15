"""Pydantic models for the LLMO analysis API.

Field names are kept in camelCase to match app/lib/types.ts's
AnalysisResult exactly, so Next.js can consume the response without a
transformation layer. See docs/07_decisions.md for why.
"""

from typing import Literal

from pydantic import BaseModel

Trend = Literal["up", "down", "flat"]
Sentiment = Literal["positive", "neutral", "negative"]
Priority = Literal["high", "medium", "low"]

# Whether a given AnalysisResult section was actually computed
# ("real"), is still fixed placeholder data ("mock"), or couldn't be
# computed because its input couldn't be obtained ("unavailable" —
# e.g. every url in `urls` failed to fetch). Tracked per section — see
# docs/07_decisions.md for why a single top-level isMock flag was
# replaced with this. "unavailable" is distinct from a "real" section
# that legitimately computed zero results (e.g. `documents: []`).
SectionStatus = Literal["mock", "real", "unavailable"]

# Where the text corpus fed into the (co-occurrence) analysis came
# from. dataforseo/common_crawl are reserved for future data sources.
DocumentsSource = Literal[
    "development_sample", "user_provided", "web_fetch", "dataforseo", "common_crawl"
]

# Distinct from DocumentsSource above: DocumentsSource summarizes the
# whole /analyze response, while DocumentSourceType tags one Document
# at a time (see Document below). The two may be unified later — see
# docs/11_architecture_v1.md "4. Document Pipeline".
DocumentSourceType = Literal[
    "user_provided", "web_fetch", "development_sample", "common_crawl", "dataforseo"
]

MAX_BRAND_NAME_LENGTH = 200

# documents[] input limits (requirement: count / per-item / total).
MAX_DOCUMENTS_COUNT = 50
MAX_DOCUMENT_LENGTH = 5000
MAX_TOTAL_DOCUMENTS_LENGTH = 50_000

# urls[] input limit.
MAX_URLS = 10


class AnalysisSectionStatuses(BaseModel):
    summary: SectionStatus
    cooccurrenceRanking: SectionStatus
    contextAnalysis: SectionStatus
    aiOverviewComparison: SectionStatus
    improvements: SectionStatus


class UrlFetchResult(BaseModel):
    url: str
    success: bool
    error: str | None = None


class Document(BaseModel):
    """A single unit of analyzable text, normalized across data
    sources (Common Crawl / DataForSEO providers will produce these
    too once implemented, without the Analyzer needing to know the
    difference). See docs/11_architecture_v1.md "4. Document Pipeline".
    """

    id: str
    sourceType: DocumentSourceType
    sourceUrl: str | None = None
    title: str | None = None
    domain: str | None = None
    fetchedAt: str
    text: str
    metadata: dict[str, object] | None = None


class AnalysisMeta(BaseModel):
    sections: AnalysisSectionStatuses
    documentsSource: DocumentsSource
    generatedAt: str
    # Present only when documentsSource is "web_fetch".
    urlFetchResults: list[UrlFetchResult] | None = None
    # Summary of the Document[] actually processed (see Document
    # above). Kept optional for schema flexibility, but in practice
    # always populated now that every documentsSource (including
    # development_sample) is wrapped as Document[].
    documentCount: int | None = None
    sourceTypes: list[DocumentSourceType] | None = None


class SentimentBreakdown(BaseModel):
    positive: int
    neutral: int
    negative: int


class BrandSummary(BaseModel):
    brandName: str
    visibilityScore: int
    totalMentions: int
    sentimentBreakdown: SentimentBreakdown
    topPlatforms: list[str]
    summaryText: str


class CooccurrenceKeyword(BaseModel):
    keyword: str
    count: int
    trend: Trend


class ContextAnalysisItem(BaseModel):
    context: str
    description: str
    sentiment: Sentiment
    exampleQuote: str


class AIOverviewComparisonItem(BaseModel):
    platform: str
    mentioned: bool
    rank: int | None
    summary: str


class ImprovementSuggestion(BaseModel):
    title: str
    description: str
    priority: Priority


class AnalysisResult(BaseModel):
    brandName: str
    summary: BrandSummary
    cooccurrenceRanking: list[CooccurrenceKeyword]
    contextAnalysis: list[ContextAnalysisItem]
    aiOverviewComparison: list[AIOverviewComparisonItem]
    improvements: list[ImprovementSuggestion]
    meta: AnalysisMeta


class AnalyzeRequest(BaseModel):
    brandName: str | None = None
    # Priority when multiple are given: documents > urls > development
    # sample. An explicit [] for documents means "analyze zero
    # documents" (yields an empty cooccurrenceRanking, not an error).
    documents: list[str] | None = None
    urls: list[str] | None = None


class ErrorResponse(BaseModel):
    error: str
