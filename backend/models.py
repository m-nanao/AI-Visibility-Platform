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

# Which data source aiOverviewComparison is built from. See
# services/ai_overview_provider.py — "mock" (fixed dev data, default),
# "off" (section disabled, section status "unavailable"), or
# "dataforseo" (not yet implemented in this task; never calls the
# external API, also reports "unavailable"). Selected via the
# AI_OVERVIEW_PROVIDER_MODE env var, optionally overridden per-request
# via AnalyzeRequest.aiOverviewMode when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true.
AiOverviewProviderMode = Literal["mock", "off", "dataforseo"]

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


class DocumentChunk(BaseModel):
    """A single chunk of one Document's `text` (see Document above),
    sized for future context-analysis/Embedding use. See
    docs/11_architecture_v1.md "4. Document Pipeline" — the Pipeline's
    "Chunker" stage. Internal processing shape only: never sent to the
    frontend in bulk (only a count, via AnalysisMeta.chunkCount).
    """

    id: str
    documentId: str
    sourceType: DocumentSourceType
    sourceUrl: str | None = None
    title: str | None = None
    domain: str | None = None
    chunkIndex: int
    text: str
    charStart: int
    charEnd: int
    metadata: dict[str, object] | None = None


class AIOverviewProviderInfo(BaseModel):
    """Reports which aiOverviewComparison provider actually ran, and
    why — see services/ai_overview_provider.py. Not shown in the UI
    yet (that's a future task); exists so callers/logs/tests can tell
    "mock", "off", and "not yet implemented (dataforseo)" apart
    without guessing from the section status alone.
    """

    mode: AiOverviewProviderMode
    status: SectionStatus
    reason: str


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
    # Count of DocumentChunk[] the Document[] above was split into (see
    # DocumentChunk above and services/document_chunker.py). The
    # Chunker's output isn't consumed by any Analyzer logic yet
    # (co-occurrence still reads whole Document.text) — this field
    # exists so the Chunker's presence is observable via the API ahead
    # of that, without exposing chunk text itself.
    chunkCount: int | None = None
    # Which aiOverviewComparison provider mode actually ran this
    # request (see AIOverviewProviderInfo above). Optional so existing
    # clients/tests that don't know about it aren't broken.
    aiOverviewProvider: AIOverviewProviderInfo | None = None


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
    # Optional per-request override of the aiOverviewComparison
    # provider mode (see services/ai_overview_provider.py). Only
    # honored when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true — otherwise
    # main.py ignores this and uses AI_OVERVIEW_PROVIDER_MODE instead,
    # so a request body alone can never turn on a paid provider in an
    # environment that isn't configured to allow it. An invalid value
    # (anything outside AiOverviewProviderMode) fails Pydantic
    # validation and becomes the same 400 {"error": "invalid request
    # body"} as other malformed request fields.
    aiOverviewMode: AiOverviewProviderMode | None = None


class ErrorResponse(BaseModel):
    error: str
