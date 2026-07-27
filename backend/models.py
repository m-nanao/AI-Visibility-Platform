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
# "dataforseo" (connects to DataForSEO Sandbox by default, or Live only
# for a fully-gated manual check — see AiOverviewEnvironment below for
# which one actually ran). Selected via the AI_OVERVIEW_PROVIDER_MODE
# env var, optionally overridden per-request via
# AnalyzeRequest.aiOverviewMode when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true.
AiOverviewProviderMode = Literal["mock", "off", "dataforseo"]

# Which concrete data source actually produced aiOverviewComparison —
# distinct from AiOverviewProviderMode/SectionStatus because neither
# can tell a Sandbox success apart from a Live success (both are
# mode="dataforseo", status="real"). "mock"/"off" mirror the mode of
# the same name; "sandbox"/"live" only appear when mode="dataforseo"
# and a usable AI Overview-type item was actually found; "unavailable"
# covers every dataforseo failure case (missing credentials, Live gates
# not satisfied, network/parse failure, no matching item). See
# services/ai_overview_provider.py's build_ai_overview_comparison().
AiOverviewEnvironment = Literal["mock", "sandbox", "live", "off", "unavailable"]

# Simple, rule-based classification of one AIOverviewReference — see
# services/ai_overview_provider.py's _classify_reference_category().
# "official" means the reference's domain matches (or is a subdomain
# of) one of the request's own input `urls`; the rest are matched
# against small hardcoded domain lists (Wikipedia/SNS/UGC/video/news).
# "media" is reserved for a future, more accurate media/blog heuristic
# — nothing is classified as "media" yet, it falls back to "other".
# Deliberately not a precise or exhaustive taxonomy.
ReferenceCategory = Literal[
    "official", "wikipedia", "sns", "ugc", "news", "media", "video", "other"
]

# Which data source the ChatGPT-equivalent observation card in
# aiOverviewComparison comes from. See services/chatgpt_provider.py —
# "off" (default; no OpenAI call, no card added) or "openai" (asks an
# OpenAI API model one non-browsing question about the brand). Selected
# via the CHATGPT_PROVIDER_MODE env var, optionally overridden
# per-request via AnalyzeRequest.chatgptMode when
# ALLOW_CHATGPT_MODE_OVERRIDE=true. Unlike AiOverviewProviderMode there
# is no "mock" value — when aiOverviewMode is "mock", the ChatGPT
# observation is skipped entirely regardless of chatgptMode, to avoid
# duplicating the mock fixture's own fixed "ChatGPT" card (see
# services/chatgpt_provider.py and main.py).
ChatGptProviderMode = Literal["off", "openai"]

# Whether the ChatGPT observation card was actually added this request.
# Distinct from SectionStatus (mock/real/unavailable) since ChatGPT
# observation has no "mock" state of its own — it either succeeds
# ("real"), is disabled ("off": chatgptMode is "off", or aiOverviewMode
# is "mock"), or failed/wasn't configured ("unavailable").
ChatGptStatus = Literal["real", "off", "unavailable"]

# Mirrors AiOverviewEnvironment's role for the ChatGPT observation:
# "api" when an OpenAI API call actually succeeded, "off"/"unavailable"
# otherwise. See services/chatgpt_provider.py's build_chatgpt_observation().
ChatGptEnvironment = Literal["api", "off", "unavailable"]

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
    why — see services/ai_overview_provider.py. Surfaced in the UI near
    the AI Overview比較 section (app/lib/meta-label.ts's
    getAiOverviewProviderStatusDisplay) so a DataForSEO Sandbox or Live
    response is never mistaken for the other, or for mock data.

    `environment` is optional so older clients that only know about
    `mode`/`status` keep working (they can no longer tell a Sandbox
    success from a Live success apart, but nothing breaks); new
    clients should prefer it over inferring from `mode`/`status`.
    """

    mode: AiOverviewProviderMode
    status: SectionStatus
    reason: str
    environment: AiOverviewEnvironment | None = None


class ChatGptProviderInfo(BaseModel):
    """Reports whether the ChatGPT-equivalent observation card was
    added to aiOverviewComparison this request, and why — see
    services/chatgpt_provider.py. Entirely optional/independent of
    AIOverviewProviderInfo above: a request can have a real DataForSEO
    result and no ChatGPT card (or vice versa, e.g. aiOverviewMode=off).
    """

    mode: ChatGptProviderMode
    status: ChatGptStatus
    reason: str
    environment: ChatGptEnvironment | None = None


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
    # Whether a ChatGPT-equivalent observation card was added to
    # aiOverviewComparison this request (see ChatGptProviderInfo above).
    # Independent of aiOverviewProvider — optional so existing
    # clients/tests that don't know about it aren't broken.
    chatgptProvider: ChatGptProviderInfo | None = None


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


class AIOverviewReference(BaseModel):
    """One citation/link DataForSEO's AI Overview-type item pointed at
    (see services/dataforseo_client.py's reference extraction). Every
    field is optional since DataForSEO's own reference/link shapes vary
    (an `ai_overview_reference` item and a `link_element` item don't
    carry the same fields) and a partially-populated reference is still
    worth showing rather than dropped.
    """

    title: str | None = None
    domain: str | None = None
    url: str | None = None
    text: str | None = None
    source: str | None = None
    position: str | None = None
    # category: simple rule-based classification (see ReferenceCategory
    # above and services/ai_overview_provider.py). Optional so a client
    # that doesn't know about it keeps working — added after references
    # itself, so this must stay backward-compatible on its own.
    category: ReferenceCategory | None = None


class AIOverviewReferenceCategoryCounts(BaseModel):
    """How many of an item's `references` fell into each category (see
    ReferenceCategory) — only ever built alongside `references` itself
    (see AIOverviewReferenceSummary), never sent on its own.
    """

    official: int | None = None
    wikipedia: int | None = None
    sns: int | None = None
    ugc: int | None = None
    news: int | None = None
    media: int | None = None
    video: int | None = None
    other: int | None = None


class AIOverviewReferenceSummary(BaseModel):
    """A quick "how many references, and of what kind" rollup of one
    item's `references` — see services/ai_overview_provider.py's
    _build_reference_summary(). `official`/`thirdParty` always add up
    to `total`; `categories` breaks `total` down further (every
    reference falls into exactly one category, so `categories`' values
    also sum to `total`).
    """

    total: int
    official: int
    thirdParty: int
    categories: AIOverviewReferenceCategoryCounts


class AIOverviewComparisonItem(BaseModel):
    platform: str
    mentioned: bool
    rank: int | None
    summary: str
    # The following three are optional and only ever populated by the
    # "dataforseo" provider (see services/ai_overview_provider.py) — the
    # mock fixture and "off" mode never set them, so existing clients
    # that don't know about these fields keep working unchanged.
    #
    # fullSummary: the AI Overview item's full text (cleaned of markdown
    # image/link syntax, capped at a few thousand characters — see
    # services/dataforseo_client.py's _build_full_summary), distinct from
    # `summary` above which stays a short (~200 char) excerpt.
    fullSummary: str | None = None
    # references: up to 10 deduplicated citations DataForSEO's response
    # pointed at. Never the raw DataForSEO response itself — see
    # services/dataforseo_client.py's module docstring.
    references: list[AIOverviewReference] | None = None
    # referenceSummary: a total/official/thirdParty/categories rollup of
    # `references` (see AIOverviewReferenceSummary above). None when
    # `references` is None/empty — there's nothing to summarize.
    referenceSummary: AIOverviewReferenceSummary | None = None
    # ownDomainReferenced: whether one of `references` shares a domain
    # with one of the request's input `urls` (a simple domain-string
    # match, not a content check). None when it can't be determined
    # (e.g. the request had no `urls`, so there is no "own domain" to
    # compare against) — see services/ai_overview_provider.py.
    ownDomainReferenced: bool | None = None


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
    # Optional per-request override of the ChatGPT-equivalent
    # observation mode (see services/chatgpt_provider.py). Only honored
    # when ALLOW_CHATGPT_MODE_OVERRIDE=true — otherwise main.py ignores
    # this and uses CHATGPT_PROVIDER_MODE instead, so a request body
    # alone can never turn on a billable OpenAI API call in an
    # environment that isn't configured to allow it. An invalid value
    # (anything outside ChatGptProviderMode) fails Pydantic validation
    # and becomes the same 400 {"error": "invalid request body"} as
    # other malformed request fields.
    chatgptMode: ChatGptProviderMode | None = None


class ErrorResponse(BaseModel):
    error: str
