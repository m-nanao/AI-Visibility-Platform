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
# "off" (section disabled, section status "unavailable"), "dataforseo"
# (env-driven: connects to DataForSEO Sandbox by default, or Live only
# for a fully-gated manual check — kept for backwards compatibility),
# "dataforseo_sandbox" (explicitly forces the Sandbox host regardless of
# DATAFORSEO_API_ENV, no Live gate involved), or "dataforseo_live"
# (explicitly requests Live — still only actually calls the Live host
# once every one of the five manual-confirmation gates holds; see
# AiOverviewEnvironment below for which one actually ran). Selected via
# the AI_OVERVIEW_PROVIDER_MODE env var, optionally overridden
# per-request via AnalyzeRequest.aiOverviewMode when
# ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true.
AiOverviewProviderMode = Literal[
    "mock", "off", "dataforseo", "dataforseo_sandbox", "dataforseo_live"
]

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

# Which data source the Claude-equivalent observation card in
# aiOverviewComparison comes from. See services/claude_provider.py —
# "off" (default; no Anthropic call, no card added) or "anthropic"
# (asks a Claude model one non-browsing question about the brand).
# Selected via the CLAUDE_PROVIDER_MODE env var, optionally overridden
# per-request via AnalyzeRequest.claudeMode when
# ALLOW_CLAUDE_MODE_OVERRIDE=true. Entirely independent of
# AiOverviewProviderMode/ChatGptProviderMode — unlike ChatGPT, this is
# never forced to "off" when aiOverviewMode is "mock", since the mock
# aiOverviewComparison fixture (services/ai_overview_provider.py's
# build_mock_ai_overview_comparison()) has no fixed "Claude" card to
# collide with.
ClaudeProviderMode = Literal["off", "anthropic"]

# Whether the Claude observation card was actually added this request.
# Mirrors ChatGptStatus's role for Claude.
ClaudeStatus = Literal["real", "off", "unavailable"]

# Mirrors ChatGptEnvironment's role for the Claude observation: "api"
# when an Anthropic API call actually succeeded, "off"/"unavailable"
# otherwise. See services/claude_provider.py's build_claude_observation().
ClaudeEnvironment = Literal["api", "off", "unavailable"]

# Which data source the Gemini-equivalent observation card in
# aiOverviewComparison comes from. See services/gemini_provider.py —
# "off" (default; no Google API call, no card added) or "google" (asks
# a Gemini model one non-browsing question about the brand). Selected
# via the GEMINI_PROVIDER_MODE env var, optionally overridden
# per-request via AnalyzeRequest.geminiMode when
# ALLOW_GEMINI_MODE_OVERRIDE=true. Entirely independent of the other
# AI observation providers — see ClaudeProviderMode's docstring for why
# this is never forced to "off" when aiOverviewMode is "mock".
GeminiProviderMode = Literal["off", "google"]

# Whether the Gemini observation card was actually added this request.
# Mirrors ChatGptStatus's role for Gemini.
GeminiStatus = Literal["real", "off", "unavailable"]

# Mirrors ChatGptEnvironment's role for the Gemini observation: "api"
# when a Google Gemini API call actually succeeded, "off"/"unavailable"
# otherwise. See services/gemini_provider.py's build_gemini_observation().
GeminiEnvironment = Literal["api", "off", "unavailable"]

# Task 6-D-1 (feature/recognition-level-classification): how
# specifically a single-call AI observation provider (ChatGPT/Claude/
# Gemini — never Google AI Mode/DataForSEO, which is search-based, not
# a model self-report) claims to recognize the brand, parsed from its
# own answer text by services/ai_observation_prompts.py's
# classify_recognition_level(). Five values, matching that function's
# exact label text:
# - "specific_knowledge": the model described concrete, specific
#   company information.
# - "partial_knowledge": the model described some information, but
#   signaled it was incomplete/uncertain.
# - "unidentified": the model stated it could not identify the
#   specific company/brand this name refers to.
# - "name_inference_only": the model explicitly noted it was only
#   guessing from how the name sounds, not from actual knowledge.
# - "indeterminate": no reliable classification could be made — the
#   model didn't follow the requested label format, or used wording
#   that doesn't map to any of the four values above. Also the safe
#   fallback whenever parsing the label line itself fails; never
#   treated as equivalent to actual recognition.
#
# **This is the model's own self-report, never independently verified
# against any Web/official source** — a future task may cross-check it
# against Common Crawl/official-site content, but this value alone
# must never be presented as "confirmed accurate" (see
# classify_recognition_level()'s own docstring for the full caveat).
# It is also deliberately independent of the older, unrelated
# `mentioned` flag on AIOverviewComparisonItem (a simple substring
# check for the brand name appearing anywhere in the answer text, which
# can be True even for a "対象企業を識別できない" / unidentified answer
# that merely echoes the name back) — `mentioned` must never be read as
# evidence of recognition accuracy either.
RecognitionLevel = Literal[
    "specific_knowledge",
    "partial_knowledge",
    "unidentified",
    "name_inference_only",
    "indeterminate",
]

# Task 6-D-3 (feature/chatgpt-websearch-supplement): a stable,
# machine-readable discriminator for AIOverviewComparisonItem — added
# because item "G" of this task explicitly forbids branching on
# `platform`'s display string to tell the original no-search ChatGPT
# observation apart from its new Web-search-supplement counterpart.
# "single_call_no_search" is the original behavior every provider
# (ChatGPT/Claude/Gemini/DataForSEO/mock) has always had; only a
# ChatGPT websearch-supplement card (see
# services/chatgpt_websearch_provider.py) ever uses
# "websearch_supplement". None (the field's default) means "predates
# this distinction" — every pre-existing saved history row and every
# non-ChatGPT provider card.
ObservationMethod = Literal["single_call_no_search", "websearch_supplement"]

# Task 6-D-3: outcome of attempting (or not attempting) ChatGPT's
# conditional Web-search supplement for this request — see
# services/chatgpt_websearch_provider.py. Deliberately enumerates every
# reason a supplement attempt did NOT happen (as its own distinct
# value, not folded into a single generic "skipped"), per that task's
# "検索補完の成功・失敗・未実施理由を識別できるようにする":
# - "not_attempted": the no-search ChatGPT observation itself never
#   produced a recognitionLevel to evaluate (e.g. ChatGPT mode "off",
#   or the no-search call itself failed) — nothing to decide on.
# - "disabled": CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED is not true.
# - "quota_enforcement_disabled": this request's quota enforcement
#   itself is off (the ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA escape hatch) —
#   the websearch supplement never runs in that combination either,
#   so it can never be used to bypass its own quota check.
# - "no_credentials": OPENAI_API_KEY is not configured.
# - "recognition_level_not_eligible": the no-search observation's
#   recognitionLevel was "specific_knowledge" (no supplement needed) or
#   "indeterminate" (deliberately never auto-searched — see
#   `reason` for which).
# - "quota_rejected": reserve_websearch_quota_for_analysis_run() raised
#   AnalysisQuotaExceededError (daily/monthly limit — 0 by default —
#   already reached).
# - "already_reserved": the same (analysis_run_id, "openai_websearch")
#   pair already has a reservation on record (should not normally
#   happen for a single /analyze request, but guards against any
#   future retry path).
# - "run_invalid": reserve_websearch_quota_for_analysis_run() rejected
#   the run/project/user combination itself (should not normally
#   happen here, since this only ever runs against the exact run/
#   project/user this same request just validated, but surfaced
#   distinctly rather than silently swallowed).
# - "reservation_error": a genuine DB/connection failure while
#   reserving quota.
# - "real": the websearch-supplement API call was attempted and
#   produced a usable answer (see `searched` on
#   ChatGptWebsearchProviderInfo for whether the model's response
#   indicates the web_search tool was actually invoked).
# - "unavailable": quota was successfully reserved, but the API call
#   itself failed (network/timeout/non-200/unreadable response) — the
#   reserved quota slot is never refunded (see that provider module's
#   docstring for why).
ChatGptWebsearchStatus = Literal[
    "not_attempted",
    "disabled",
    "quota_enforcement_disabled",
    "no_credentials",
    "recognition_level_not_eligible",
    "quota_rejected",
    "already_reserved",
    "run_invalid",
    "reservation_error",
    "real",
    "unavailable",
]

# Whether /analyze should try to add supplementary Document(s) from
# Common Crawl (see services/common_crawl_index.py /
# common_crawl_warc.py / common_crawl_document_provider.py and
# docs/13_common_crawl_mvp_design.md). "off" (default) does nothing;
# "domain" searches Common Crawl's Index API for the request's domain
# (see AnalyzeRequest.commonCrawlDomain below) and tries to fetch/build
# Documents from up to main.py's COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE
# usable candidates. Unlike
# AiOverviewProviderMode/ChatGptProviderMode there is no separate
# ALLOW_*_OVERRIDE env gate — the request field is honored directly,
# but only ever does anything when COMMON_CRAWL_ENABLED=true (see
# main.py._build_common_crawl_documents()), so a request body alone
# still can't turn this on in an environment not configured to allow
# it.
CommonCrawlProviderMode = Literal["off", "domain"]

# Whether the Common Crawl "補完" flow actually added a Document this
# request. "off": commonCrawlMode was "off", or COMMON_CRAWL_ENABLED is
# not true. "real": a Document was added. "unavailable": commonCrawlMode
# was "domain" and Common Crawl is enabled, but the domain couldn't be
# determined, the Index search failed/found nothing, or every candidate
# failed to fetch/convert into a Document.
CommonCrawlProviderStatus = Literal["off", "real", "unavailable"]

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

    `recognitionLevel`/`promptVersion` (Task 6-D-1,
    feature/recognition-level-classification) are both optional —
    `None` on every pre-existing saved history row (neither field
    existed before this task) and whenever no actual model call
    happened (mode="off", or a gate/API failure before any text was
    returned) — so existing clients/tests that don't know about them
    keep working unchanged. See models.RecognitionLevel's own
    docstring for why `recognitionLevel` must never be read as a
    verified fact.
    """

    mode: ChatGptProviderMode
    status: ChatGptStatus
    reason: str
    environment: ChatGptEnvironment | None = None
    recognitionLevel: RecognitionLevel | None = None
    promptVersion: str | None = None


class ChatGptWebsearchProviderInfo(BaseModel):
    """Reports whether ChatGPT's conditional Web-search supplement
    (Task 6-D-3, feature/chatgpt-websearch-supplement) was attempted
    for this request, and why — see
    services/chatgpt_websearch_provider.py. Entirely optional/
    independent of ChatGptProviderInfo above (the no-search
    observation): a request can have a real no-search ChatGPT card and
    no websearch-supplement card (the common case — most
    recognitionLevels never trigger it, and the feature defaults to
    disabled), or, on success, both cards side by side in
    `aiOverviewComparison`, distinguished by
    AIOverviewComparisonItem.observationMethod — never by `platform`'s
    display string.

    `recognitionLevelAtTrigger` records the no-search observation's own
    recognitionLevel at the moment this decision was made — purely
    informational (so a saved history row shows *why* the supplement
    did or didn't run), never re-derived from
    ChatGptProviderInfo.recognitionLevel at read time (that field could
    change meaning in a future task; this one is a frozen snapshot).

    `searched` is None unless `status == "real"` — see
    ChatGptWebsearchStatus's own docstring on why a successful API call
    does not necessarily mean the web_search tool was actually invoked
    (the model can answer without searching even when the tool is
    offered); True only when the response's own `web_search_call`
    output item reports `status == "completed"`.

    Absent entirely (None) on every pre-existing saved history row —
    this field didn't exist before Task 6-D-3.
    """

    status: ChatGptWebsearchStatus
    reason: str
    recognitionLevelAtTrigger: RecognitionLevel | None = None
    searched: bool | None = None


# Task 6-D-4A-2 (feature/claude-websearch-supplement): outcome of
# attempting (or not attempting) Claude's conditional Web-search
# supplement for this request — see
# services/claude_websearch_provider.py. Deliberately named/valued the
# same way as ChatGptWebsearchStatus above (per this task's own
# "命名は既存ChatGPT実装との整合性を優先する" instruction) wherever the
# underlying reason is the same concept; "reservation_error" and
# "unavailable" etc. all carry identical meanings to their ChatGPT
# counterparts. See that Literal's own docstring for what each value
# means — not repeated verbatim here to avoid the two drifting out of
# sync under future edits to only one of them.
ClaudeWebsearchStatus = Literal[
    "not_attempted",
    "disabled",
    "quota_enforcement_disabled",
    "no_credentials",
    "recognition_level_not_eligible",
    "quota_rejected",
    "already_reserved",
    "run_invalid",
    "reservation_error",
    "real",
    "unavailable",
]


class ClaudeWebsearchProviderInfo(BaseModel):
    """Reports whether Claude's conditional Web-search supplement
    (Task 6-D-4A-2, feature/claude-websearch-supplement) was attempted
    for this request, and why — see
    services/claude_websearch_provider.py. Entirely optional/
    independent of ClaudeProviderInfo above (the no-search
    observation): mirrors ChatGptWebsearchProviderInfo's own docstring
    for the full reasoning (recognitionLevelAtTrigger is a frozen
    snapshot, `searched` is None unless status=="real", absent on every
    pre-existing saved history row).

    `searched` is True only when Claude's response contained an actual
    (non-error) web_search_tool_result content block — see
    services/claude_websearch_client.py's _parse_websearch_response()
    for the exact signal. `searchErrorCode` is set only when Claude
    attempted a search but Anthropic returned a
    `web_search_tool_result_error` instead of results (e.g.
    "max_uses_exceeded", "too_many_requests", "unavailable" — see
    Anthropic's web-search-tool documentation) — independent of
    `searched` (False in that case) and never set when no search was
    attempted at all.

    `model` records which Claude model actually served this card —
    Task 6-D-4A-2 item 1's own requirement ("検索補完用モデルが既存モデ
    ルと異なる場合、結果メタデータに使用モデルを識別可能な形で記録す
    る"): services/claude_websearch_settings.py's model default
    deliberately differs from services/claude_settings.py's (see that
    module's own docstring for why), so this field is always populated
    whenever a websearch-supplement attempt actually reaches the gate
    that reads the configured model (i.e. whenever `status` is neither
    "not_attempted" nor "disabled" nor "quota_enforcement_disabled" —
    see services/claude_websearch_provider.py for the exact gate
    order), even on an unsuccessful attempt, so a saved history row
    always shows which model was configured at the time, not only on
    success.
    """

    status: ClaudeWebsearchStatus
    reason: str
    recognitionLevelAtTrigger: RecognitionLevel | None = None
    searched: bool | None = None
    searchErrorCode: str | None = None
    model: str | None = None


class ClaudeProviderInfo(BaseModel):
    """Reports whether the Claude-equivalent observation card was added
    to aiOverviewComparison this request, and why — see
    services/claude_provider.py. Entirely optional/independent of
    AIOverviewProviderInfo/ChatGptProviderInfo above.

    `recognitionLevel`/`promptVersion`: see
    ChatGptProviderInfo's own doc for this Task 6-D-1 addition — same
    optionality/backward-compatibility reasoning applies identically
    here.
    """

    mode: ClaudeProviderMode
    status: ClaudeStatus
    reason: str
    environment: ClaudeEnvironment | None = None
    recognitionLevel: RecognitionLevel | None = None
    promptVersion: str | None = None


class GeminiProviderInfo(BaseModel):
    """Reports whether the Gemini-equivalent observation card was added
    to aiOverviewComparison this request, and why — see
    services/gemini_provider.py. Entirely optional/independent of the
    other AI observation providers above.

    `recognitionLevel`/`promptVersion`: see
    ChatGptProviderInfo's own doc for this Task 6-D-1 addition — same
    optionality/backward-compatibility reasoning applies identically
    here.
    """

    mode: GeminiProviderMode
    status: GeminiStatus
    reason: str
    environment: GeminiEnvironment | None = None
    recognitionLevel: RecognitionLevel | None = None
    promptVersion: str | None = None


class CommonCrawlProviderInfo(BaseModel):
    """Reports whether the Common Crawl "補完" flow added a
    supplementary Document to this request, and why — see
    main.py._build_common_crawl_documents() and
    docs/13_common_crawl_mvp_design.md. Entirely independent of
    aiOverviewProvider/chatgptProvider — a request can succeed/fail on
    each independently, and this never touches `documentsSource` or the
    section statuses above (Common Crawl is a supplementary input, not
    a replacement for the primary documents/urls/development_sample
    source). At most main.py's COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE
    (currently 3) Documents are ever added this way — `documentCount`
    ranges from 0 up to that limit.
    """

    mode: CommonCrawlProviderMode
    status: CommonCrawlProviderStatus
    reason: str
    domain: str | None = None
    crawlIndex: str | None = None
    candidateCount: int = 0
    documentCount: int = 0
    # The source URL of each Common Crawl Document actually added to
    # this request's analysis (never a candidate that was found but
    # failed to fetch/convert) — lets the UI/依頼者 see exactly which
    # pages were analyzed, for transparency and debugging ahead of any
    # future increase to COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE. Only
    # ever populated on a "real" result; "off"/"unavailable" leave this
    # at its default empty list. De-duplicated (in the unlikely event
    # the Index API returns more than one capture of the same URL among
    # the successfully-fetched candidates) — URLs only, never HTML/WARC
    # body text or any other candidate metadata.
    analyzedUrls: list[str] = []


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
    # Task 6-D-3 (feature/chatgpt-websearch-supplement) — whether
    # ChatGPT's conditional Web-search supplement was attempted, and
    # why (see ChatGptWebsearchProviderInfo above). Independent of
    # chatgptProvider — optional so existing clients/tests, and every
    # saved history row predating this task, keep working unchanged.
    chatgptWebsearchProvider: ChatGptWebsearchProviderInfo | None = None
    # Whether a Claude-equivalent observation card was added to
    # aiOverviewComparison this request (see ClaudeProviderInfo above).
    # Independent of the other AI observation providers — optional so
    # existing clients/tests that don't know about it aren't broken.
    claudeProvider: ClaudeProviderInfo | None = None
    # Task 6-D-4A-2 (feature/claude-websearch-supplement) — whether
    # Claude's conditional Web-search supplement was attempted, and
    # why (see ClaudeWebsearchProviderInfo above). Independent of
    # claudeProvider — optional so existing clients/tests, and every
    # saved history row predating this task, keep working unchanged.
    claudeWebsearchProvider: ClaudeWebsearchProviderInfo | None = None
    # Whether a Gemini-equivalent observation card was added to
    # aiOverviewComparison this request (see GeminiProviderInfo above).
    # Independent of the other AI observation providers — optional so
    # existing clients/tests that don't know about it aren't broken.
    geminiProvider: GeminiProviderInfo | None = None
    # Whether a supplementary Common Crawl Document was added to this
    # request's Document[] (see CommonCrawlProviderInfo above).
    # Independent of aiOverviewProvider/chatgptProvider — optional so
    # existing clients/tests that don't know about it aren't broken.
    commonCrawlProvider: CommonCrawlProviderInfo | None = None


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


class WebsearchCitationAnnotation(BaseModel):
    """Task 6-D-3D follow-up (feature/chatgpt-full-text-citations): one
    *raw* `url_citation` annotation from ChatGPT's Web-search
    supplement, exactly as OpenAI's Responses API returned it — see
    services/chatgpt_websearch_client.py's WebsearchCitationAnnotation
    (the internal dataclass this Pydantic model mirrors field-for-
    field) for the full extraction contract.

    **Deliberately distinct from AIOverviewReference** (the
    de-duplicated, normalized *display* list on
    AIOverviewComparisonItem.references): `url` here is OpenAI's exact
    original URL, including any tracking parameters — never
    normalized, never de-duplicated. Multiple entries can (and often
    do) share the same `url` when the model's answer cites the same
    source more than once; that repetition is itself data a future
    citation-analysis task would need (how many times was this source
    actually cited), so it is preserved here rather than collapsed.
    `startIndex`/`endIndex` are OpenAI's own character-offset fields
    for which span of the answer text this citation backs, kept as-is
    when present — None (not 0) when absent, so "no position
    information" is never confused with "position zero".

    This model exists purely as structured storage for a future task;
    nothing in this codebase reads it to build any UI yet.
    """

    url: str
    title: str | None = None
    startIndex: int | None = None
    endIndex: int | None = None


class ClaudeWebsearchCitationAnnotation(BaseModel):
    """Task 6-D-4A-2 (feature/claude-websearch-supplement): one *raw*
    `web_search_result_location` citation from Claude's Web-search
    supplement, exactly as Anthropic's Messages API returned it — see
    services/claude_websearch_client.py's ClaudeWebsearchCitationAnnotation
    (the internal dataclass this Pydantic model mirrors field-for-
    field) for the full extraction contract.

    **Deliberately a separate model from WebsearchCitationAnnotation
    above, not a shared/reused one** — Anthropic's citation shape is
    not the same as OpenAI's: there is no numeric start/end character
    offset on the Anthropic side at all (Claude's Messages API never
    returns one), so this model has no `startIndex`/`endIndex` fields;
    inventing them here would misrepresent data Anthropic never sent.
    `citedText` (Anthropic's own `cited_text`, up to 150 characters) is
    the closest available signal for "which part of the answer this
    citation backs" and is kept as Anthropic returned it. `url`/`title`
    are the exact original values, never normalized/de-duplicated —
    see ClaudeWebsearchCitation (services/claude_websearch_client.py)
    for the separate, normalized/de-duplicated display entry. Multiple
    entries can share the same `url` when the answer cites the same
    source more than once; never collapsed here. Anthropic's own
    `encrypted_index` (an opaque token for resuming a multi-turn
    conversation) is deliberately not a field on this model — this
    feature never resends a prior response's content, so that token
    has no reuse value and no analytic purpose here.

    This model exists purely as structured storage for a future task;
    nothing in this codebase reads it to build any UI yet.
    """

    url: str
    title: str | None = None
    citedText: str | None = None


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
    # The following three are optional and only ever populated by the
    # Gemini observation provider (see services/gemini_client.py) —
    # every other provider (mock, DataForSEO, ChatGPT, Claude) leaves
    # them None, so existing clients/old saved history that don't know
    # about these fields keep working unchanged.
    #
    # finishReason: Gemini's own candidates[0].finishReason value
    # verbatim (e.g. "STOP", "MAX_TOKENS", "SAFETY", "RECITATION",
    # "OTHER") — never used to change /analyze's control flow beyond
    # deciding isTruncated below, just surfaced for debugging. None
    # when Gemini didn't include one, or for every non-Gemini item.
    finishReason: str | None = None
    # isTruncated: a heuristic-only signal (never a hard error) that
    # this answer may have been cut off mid-way — see
    # services/gemini_client.py's _is_likely_truncated(). True doesn't
    # mean "Gemini has no information about this brand"; it means this
    # one observation attempt's output may be incomplete.
    isTruncated: bool | None = None
    # note: a short, safe-to-display explanation shown alongside the
    # card when isTruncated is True (see services/gemini_client.py's
    # TRUNCATION_NOTE) — None when there's nothing to add.
    note: str | None = None
    # Task 6-D-3 (feature/chatgpt-websearch-supplement) — see
    # ObservationMethod's own docstring. None for every pre-existing
    # saved history row and every card besides a ChatGPT websearch-
    # supplement one.
    observationMethod: ObservationMethod | None = None
    # Task 6-D-3D (feature/chatgpt-full-text-citations) — True only
    # when the ChatGPT no-search or websearch-supplement client's own
    # storage-safety ceiling (services/chatgpt_client.py's
    # _FULL_SUMMARY_SAFETY_MAX_CHARS, 20000 — see that constant's own
    # docstring) actually had to shorten `fullSummary`. Deliberately
    # independent of `isTruncated` above: that field means "OpenAI's
    # own API response was reported incomplete"; this one means "our
    # own storage ceiling cut an otherwise-complete response" — the
    # two are never derived from each other, and either, neither, or
    # (in theory) both can be true at once. None for every other
    # provider and for every pre-existing saved history row.
    fullSummaryTruncated: bool | None = None
    # Task 6-D-3D follow-up (feature/chatgpt-full-text-citations) —
    # only ever populated by the ChatGPT Web-search-supplement card;
    # None for every other provider and every pre-existing saved
    # history row. See WebsearchCitationAnnotation's own docstring for
    # why this is deliberately separate from (and more complete than)
    # `references` below: `references` is the de-duplicated,
    # normalized display list; `citationAnnotations` is the raw,
    # pre-de-duplication data (including repeats and original,
    # unnormalized URLs) kept for a future citation-analysis task.
    citationAnnotations: list[WebsearchCitationAnnotation] | None = None
    # The *true* total number of raw url_citation annotations OpenAI's
    # response contained, before
    # services/chatgpt_websearch_client.py's own
    # _MAX_RAW_CITATION_ANNOTATIONS storage-safety ceiling is applied.
    # Comparing this to `len(citationAnnotations)` is how a reader
    # detects whether that ceiling actually dropped anything — never
    # silently. None whenever `citationAnnotations` itself is None.
    citationAnnotationsTotalCount: int | None = None
    # True when `references` below had to drop one or more distinct
    # (post-normalization) URLs because there were more than
    # services/chatgpt_websearch_client.py's own `_MAX_CITATIONS` (10)
    # — i.e. `references` is not the complete set of distinct sources
    # actually cited. Independent of `citationAnnotationsTotalCount`
    # above (that one is about the raw annotation list's own storage
    # ceiling; this one is about the de-duplicated display list's own,
    # smaller cap). None for every provider other than ChatGPT's
    # Web-search supplement.
    citationsTruncated: bool | None = None
    # Task 6-D-4A-2 (feature/claude-websearch-supplement) — the raw,
    # pre-de-duplication citation data for a Claude Web-search
    # supplement card, analogous to citationAnnotations above but built
    # from Anthropic's own citation shape (url/title/cited_text — no
    # numeric start/end offset exists on the Anthropic side; see
    # ClaudeWebsearchCitationAnnotation's own docstring). Deliberately
    # a separate field from citationAnnotations rather than a shared
    # one: the two providers' raw annotation shapes are not
    # interchangeable, and OpenAI's fields are never forced onto
    # Claude's data (or vice versa). None for every other provider and
    # every pre-existing saved history row. `citationsTruncated` above
    # is reused as-is for the Claude card too — its meaning ("the
    # display `references` list dropped some URLs") is identical
    # regardless of provider.
    claudeCitationAnnotations: list[ClaudeWebsearchCitationAnnotation] | None = None
    # The *true* total number of raw web_search_result_location
    # citations Anthropic's response contained, before
    # services/claude_websearch_client.py's own
    # _MAX_RAW_CITATION_ANNOTATIONS storage-safety ceiling is applied —
    # same role as citationAnnotationsTotalCount above, for the Claude
    # card. None whenever claudeCitationAnnotations itself is None.
    claudeCitationAnnotationsTotalCount: int | None = None
    # Task 6-D-4A-2 final review: the actual model id that produced
    # *this* card — a generic, provider-agnostic field (not
    # "claudeModel"/"chatgptModel") since any provider's card can carry
    # one, and a future provider should never need a new field to
    # expose this. Added specifically because Claude's no-search card
    # (services/claude_provider.py, model from
    # services/claude_settings.py) and its Web-search-supplement card
    # (services/claude_websearch_provider.py, model from
    # services/claude_websearch_settings.py — deliberately a different
    # default, see that module's own docstring on claude-sonnet-4-5's
    # deprecation) can legitimately be served by two different models
    # for the same brand in the same request; without this field a
    # reader comparing the two cards' answers would have no way to
    # know a model difference (not just a search-vs-no-search
    # difference) might explain any gap between them. None for every
    # provider/card that predates this field, and for a card whose
    # provider was never reached far enough to know which model was
    # configured (e.g. a gate rejection with no item at all).
    model: str | None = None


# Whether services/web_ai_gap.py could build a meaningful comparison —
# "real" when both a Web-side representative context and at least one
# real single-shot AI observation were available, "unavailable"
# otherwise (missing either side means there is nothing to compare).
# Distinct from SectionStatus: there is no "mock" state here, since
# this section is never fixed placeholder data — it's either computed
# from what's actually available this request, or not computed at all.
WebAiGapStatus = Literal["real", "unavailable"]

# Where WebAiGapWebContext.summary's representative text came from.
# services/web_ai_gap.py only ever picks a single Document (preferring
# "common_crawl" over "web_fetch" — see its module docstring), so only
# those two values are actually produced today; "mixed"/"unknown" are
# reserved for a future version that might blend multiple Documents.
WebAiGapWebSourceType = Literal["common_crawl", "web_fetch", "mixed", "unknown"]

# Which AI observation a WebAiGapAiContext entry summarizes. Mirrors
# the platform labels already used elsewhere (ChatGptProviderInfo.mode
# "openai" etc.) but as a short, stable key rather than each provider's
# display-oriented AIOverviewComparisonItem.platform string (e.g.
# "ChatGPT (OpenAI API)") — see services/web_ai_gap.py's
# _classify_ai_platform().
WebAiGapPlatform = Literal["chatgpt", "claude", "gemini", "ai_overview"]


class WebAiGapWebContext(BaseModel):
    """A short, representative excerpt of what the Web-side Document[]
    says about the brand — see services/web_ai_gap.py. Never the full
    Document text, and never HTML/WARC body (same discipline as
    CommonCrawlProviderInfo above)."""

    summary: str
    sourceType: WebAiGapWebSourceType
    sourceUrl: str | None = None


class WebAiGapAiContext(BaseModel):
    """One AI observation's short excerpt, reused as-is from the
    matching AIOverviewComparisonItem.summary already computed earlier
    in /analyze (see services/web_ai_gap.py) — no new API call. `status`
    is always "real": services/web_ai_gap.py only ever builds an entry
    for a platform that actually produced a real single-shot
    observation this request (off/unavailable/mock items are excluded
    entirely, never included with a different status), so this field
    exists only to make that guarantee explicit in the response shape
    rather than to distinguish states.
    """

    platform: WebAiGapPlatform
    summary: str
    status: Literal["real"] = "real"


class WebAiGapResult(BaseModel):
    """"Web上の説明とAI回答のズレ" — an MVP, rule-based comparison
    between the Web-side information environment (Common Crawl/
    web_fetch Document[], already gathered for cooccurrenceRanking) and
    the AI-side single-shot observations (ChatGPT/Claude/Gemini/AI
    Overview, already gathered for aiOverviewComparison) — see
    services/web_ai_gap.py. Added per a依頼者 review request to help
    explain *why* Web content and AI answers might read differently,
    and what to adjust on the Web side to narrow that gap.

    No new external API call of any kind (no new AI summarization
    call, no new Common Crawl/web fetch) — every field here is built
    from Document[]/cooccurrenceRanking/aiOverviewComparison already
    computed elsewhere in the same /analyze request. Optional on
    AnalysisResult so older saved history (predating this field)
    keeps parsing unchanged — see AnalysisResult.webAiGap below.
    """

    status: WebAiGapStatus
    # None when status is "unavailable" (nothing to compare).
    webContext: WebAiGapWebContext | None = None
    aiContexts: list[WebAiGapAiContext] = []
    # None when status is "unavailable", or when there was nothing
    # distinctive to report on either side.
    gapSummary: str | None = None
    suggestions: list[str] = []
    # A short, always-present reminder that this is a rough, auxiliary
    # comparison — never a claim about what an AI has "learned" or
    # "understood" (see services/web_ai_gap.py's WEB_AI_GAP_NOTE /
    # WEB_AI_GAP_UNAVAILABLE_NOTE for the exact wording used for each
    # status).
    note: str


class AiGapActionRecommendation(BaseModel):
    """One concrete, evidence-based improvement action derived from an
    AI-based Web/AI gap comparison — see
    services/ai_gap_comparison.py's generation/extraction logic and
    docs/39_ai_gap_comparison_design.md. Unlike the rule-based
    `ImprovementSuggestion` above (fixed wording, always generated
    during `/analyze`), these come from the same single Anthropic call
    as the rest of `WebAiGapAiComparison` — never a second request.

    `title`/`issue`/`action`/`evidence` are required and non-blank —
    an item missing any of these is dropped entirely rather than
    guessed at (see services/ai_gap_comparison.py's
    `_coerce_action_recommendations()`, fix/ai-gap-action-
    recommendations-missing). `target` (the suggested page/location)
    is optional and left `None` rather than fabricated when the model
    didn't name one — never invent an unconfirmed page. `priority`/
    `verification` fall back to a safe, generic default
    ("medium"/a standard "re-observe and check" instruction) when the
    model omits them, since discarding an otherwise complete,
    evidence-based recommendation over one missing non-critical field
    was found to silently drop every recommendation in production
    (likely due to limited output budget — see that module's
    docstring).
    """

    title: str
    issue: str
    action: str
    target: str | None = None
    evidence: str
    priority: Priority = "medium"
    verification: str = "施策実施後、同じ質問で改めてAI観測を行い、説明内容が変化したか確認する。"


class WebAiGapAiComparison(BaseModel):
    """AI-generated (not rule-based) comparison of the same Web excerpt
    vs. AI observation summaries used by WebAiGapResult above — see
    services/ai_gap_comparison.py and
    docs/39_ai_gap_comparison_design.md. Generated only on-demand, by
    POST /analysis-runs/{id}/web-ai-gap/ai-comparison, never during a
    normal `/analyze` request.

    Stored as `result_json.webAiGapAiComparison`, a field separate from
    (and never overwriting) `result_json.webAiGap` — docs/39's DB
    design 案C — so a failed/low-quality AI comparison can never take
    down the existing rule-based comparison. Only ever constructed by
    a successful services/ai_gap_comparison.py call (a failed attempt
    is never persisted — see that module), so `status` has no
    "unavailable" value here, unlike WebAiGapStatus above.

    `method="ai_comparison_text_fallback"` (fix/ai-gap-comparison-
    text-fallback) marks a result built from Claude's raw natural-
    language output when no JSON object could be found in it at all
    (REASON_NO_JSON_OBJECT_FOUND in services/ai_gap_comparison.py) —
    the list fields are empty and `textSummary` carries the (possibly
    truncated) natural-language text instead. This is still a single
    Anthropic call's output, never a second request.

    `method="ai_comparison_json_like_fallback"` (fix/ai-gap-comparison-
    json-like-fallback-display) marks a result built by best-effort
    regex extraction of known fields out of JSON-shaped-but-undecodable
    text (e.g. truncated mid-array) — the list/gapSummary fields that
    could be recovered are populated the same as a normal successful
    comparison, `textSummary` stays unset, and any field that couldn't
    be recovered defaults to empty/None exactly like a normal
    comparison's missing field would.

    `actionRecommendations` (feature/ai-gap-action-recommendations,
    optional, ≤3 items) carries concrete, evidence-based improvement
    actions derived from this same comparison — distinct from the
    rule-based `ImprovementSuggestion`s always generated during
    `/analyze`, and from the plain `recommendations: list[str]` above
    (short one-line hints with no evidence/priority/verification).
    See `AiGapActionRecommendation` above.
    """

    status: Literal["real"] = "real"
    method: Literal[
        "ai_comparison", "ai_comparison_text_fallback", "ai_comparison_json_like_fallback"
    ] = "ai_comparison"
    matchedPoints: list[str] = []
    webStrongAiWeak: list[str] = []
    aiStrongWebWeak: list[str] = []
    gapSummary: str | None = None
    recommendations: list[str] = []
    # Only set when method == "ai_comparison_text_fallback" — Claude's
    # raw natural-language comparison text (possibly truncated, see
    # services/ai_gap_comparison.py's MAX_TEXT_FALLBACK_LENGTH), shown
    # as-is instead of the structured list fields above.
    textSummary: str | None = None
    # AI-generated, evidence-based improvement actions derived from
    # this same comparison call (never a second Anthropic request) —
    # see services/ai_gap_comparison.py's
    # _coerce_action_recommendations() (≤3 items,
    # MAX_ACTION_RECOMMENDATIONS). `None` on older saved history that
    # predates this field, or when Claude's output has no JSON
    # structure to extract one from at all (the plain text fallback) —
    # the frontend must treat both the same as "nothing to show", not
    # an error. An empty list (as opposed to `None`) means a
    # recommendations array was present in the model's output but
    # explicitly empty, or every item in it failed validation —
    # distinct from the field never having been attempted.
    actionRecommendations: list[AiGapActionRecommendation] | None = None
    # Always the same fixed, safe-to-display reminder regardless of
    # what the model itself produced — see
    # services/ai_gap_comparison.py's CAUTION_TEXT, which overwrites
    # whatever the model returned for this field rather than trusting
    # it verbatim.
    caution: str


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
    # The saved analysis_runs.id when this analysis was persisted to
    # the DB, or None when DB save is disabled/unconfigured/failed (see
    # main.py's /analyze handler and
    # docs/23_analysis_run_id_and_post_analyze_link_design.md). A DB
    # save failure never fails /analyze itself — this field is simply
    # None in that case, same as when saving is off entirely.
    analysisRunId: str | None = None
    # "Web上の説明とAI回答のズレ" — see WebAiGapResult above and
    # services/web_ai_gap.py. Optional so old saved history (predating
    # this field) still parses/renders unchanged.
    webAiGap: WebAiGapResult | None = None
    # AI-generated comparison, generated on-demand from the history
    # detail screen only (see services/ai_gap_comparison.py) — never
    # populated by a normal `/analyze` request, so this is always None
    # immediately after analysis and only ever set later via POST
    # /analysis-runs/{id}/web-ai-gap/ai-comparison.
    webAiGapAiComparison: WebAiGapAiComparison | None = None


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
    # Optional per-request override of the Claude-equivalent
    # observation mode (see services/claude_provider.py). Only honored
    # when ALLOW_CLAUDE_MODE_OVERRIDE=true — otherwise main.py ignores
    # this and uses CLAUDE_PROVIDER_MODE instead, so a request body
    # alone can never turn on a billable Anthropic API call in an
    # environment that isn't configured to allow it. An invalid value
    # (anything outside ClaudeProviderMode) fails Pydantic validation
    # and becomes the same 400 {"error": "invalid request body"} as
    # other malformed request fields.
    claudeMode: ClaudeProviderMode | None = None
    # Optional per-request override of the Gemini-equivalent
    # observation mode (see services/gemini_provider.py). Only honored
    # when ALLOW_GEMINI_MODE_OVERRIDE=true — otherwise main.py ignores
    # this and uses GEMINI_PROVIDER_MODE instead, so a request body
    # alone can never turn on a billable Google API call in an
    # environment that isn't configured to allow it. An invalid value
    # (anything outside GeminiProviderMode) fails Pydantic validation
    # and becomes the same 400 {"error": "invalid request body"} as
    # other malformed request fields.
    geminiMode: GeminiProviderMode | None = None
    # Whether to try adding one supplementary Document from Common
    # Crawl (see CommonCrawlProviderMode above). Defaults to "off" when
    # omitted (treated the same as explicit "off" — see main.py). An
    # invalid value (anything outside CommonCrawlProviderMode) fails
    # Pydantic validation and becomes the same 400 {"error": "invalid
    # request body"} as other malformed request fields. Unlike
    # aiOverviewMode/chatgptMode there is no ALLOW_*_OVERRIDE env gate —
    # see CommonCrawlProviderMode's docstring for why that's still safe.
    commonCrawlMode: CommonCrawlProviderMode | None = None
    # The domain to search Common Crawl for when commonCrawlMode is
    # "domain" (e.g. "cybozu.co.jp"). If omitted, main.py falls back to
    # the hostname of `urls[0]` when present; if neither yields a
    # domain, the Common Crawl step reports "unavailable". Whatever
    # domain is used is still validated/normalized by
    # services/common_crawl_index.py before any HTTP request is made —
    # this field is not trusted as-is.
    commonCrawlDomain: str | None = None
    # The project this analysis should be saved under — required only
    # when ANALYZE_AUTH_REQUIRED=true (see main.py's analyze(), Task
    # 6-B2). Ignored entirely when that flag is false: the legacy
    # anonymous path always saves to the fixed default project
    # regardless of what (if anything) is sent here, exactly as before
    # this field existed. When the flag is true, this value is never
    # trusted as-is — main.py verifies the caller's JWT and checks
    # can_user_access_project() before it is ever passed to
    # save_analysis_history().
    projectId: str | None = None
    # Client-generated idempotency key for one "start analysis"
    # operation — required only when ANALYZE_AUTH_REQUIRED=true (Task
    # 6-B3, feature/sync-analyze-jwt-project-auth). Ignored entirely
    # when that flag is false, exactly like projectId above: the
    # anonymous path has no concept of request-level idempotency and
    # is completely unaffected by this field. See
    # services/analysis_history_repository.py's "Synchronous analysis
    # idempotency" section for why this can't safely be extended to
    # the anonymous path too.
    requestId: str | None = None


class ErrorResponse(BaseModel):
    error: str


# --- Analysis history read API (GET /analysis-runs, GET
# /analysis-runs/{id}) — see services/analysis_history_repository.py's
# list_analysis_runs()/get_analysis_run() and
# docs/20_analysis_history_read_api_design.md. Field names are
# camelCase to match the rest of this file's response models, even
# though these two endpoints aren't consumed by app/ yet. Entirely
# independent of AnalysisResult/AnalyzeRequest above — /analyze's
# request/response schema is unchanged by this API.


class AnalysisRunModeSummary(BaseModel):
    """Which observation providers were actually in effect for one
    saved analysis run — see services/history_mode_summary.py's
    build_mode_summary(). Shown as a short badge row on each
    GET /analysis-runs list item so a依頼者 running repeated full-ON/
    single-ON verification passes can tell similar-looking runs apart
    without opening each one's detail page.

    `aiOverview` uses the same vocabulary as AiOverviewEnvironment
    ("mock"/"sandbox"/"live"/"off"/"unavailable") plus "unknown";
    `chatgpt`/`claude`/`gemini`/`commonCrawl` use their own provider's
    status vocabulary ("real"/"off"/"unavailable") plus "unknown". Every
    field is "unknown" rather than raising when its provider info is
    missing from the saved meta_json (e.g. a run saved before that
    provider existed), so this never breaks rendering of old history.
    """

    aiOverview: str
    chatgpt: str
    claude: str
    gemini: str
    commonCrawl: str


# --- Tags / categories (feature/history-tags-categories) ---
#
# project-shared, independent of each other and of
# isImportant/isFavorite — see backend/migrations/
# 008_add_tags_and_categories.sql. A history run may have any number
# of tags (many-to-many, via analysis_run_tags) and at most one
# category (analysis_runs.category_id, nullable — "未分類" when null).


class TagItem(BaseModel):
    """One row of `tags`, or one entry of a run's `tags` list — same
    shape either way, no separate "summary" projection needed since a
    tag has nothing beyond id/projectId/name."""

    id: str
    projectId: str
    name: str


class TagListResponse(BaseModel):
    tags: list[TagItem]


class TagCreateRequest(BaseModel):
    """POST /tags body — `projectId` is required (unlike the
    history-read endpoints, there is no implicit "current project" for
    a write; see main.py's _resolve_jwt_only_project_write_access())."""

    projectId: str
    name: str


class TagRenameRequest(BaseModel):
    """PATCH /tags/{id} body — renaming never touches projectId; a tag
    cannot be moved to a different project."""

    name: str


class CategoryItem(BaseModel):
    id: str
    projectId: str
    name: str


class CategoryListResponse(BaseModel):
    categories: list[CategoryItem]


class CategoryCreateRequest(BaseModel):
    projectId: str
    name: str


class CategoryRenameRequest(BaseModel):
    name: str


class AnalysisRunTagAttachRequest(BaseModel):
    """POST /analysis-runs/{id}/tags body."""

    tagId: str


class AnalysisRunCategorySetRequest(BaseModel):
    """PUT /analysis-runs/{id}/category body — `categoryId: null`
    clears the run's category back to "未分類"."""

    categoryId: str | None


class AnalysisRunListItem(BaseModel):
    """One row of GET /analysis-runs's `items` — see
    docs/20_analysis_history_read_api_design.md "5. GET /analysis-runs
    の設計案". Deliberately excludes result_json/meta_json (see that
    section's "返さないもの") — use GET /analysis-runs/{id} for those.
    `modeSummary` below is a small, derived-from-meta_json exception to
    that rule, added for feature/history-delete-and-mode-badges.
    """

    id: str
    brandName: str
    canonicalDomain: str | None
    status: str
    visibilityScore: int | None
    sourceSummary: dict[str, object] | None
    startedAt: str | None
    completedAt: str | None
    createdAt: str | None
    # Optional so an existing/older frontend build that doesn't know
    # about this field keeps working unchanged (it simply ignores the
    # extra key) — see services/history_mode_summary.py's module
    # docstring for how this is computed and why it always falls back
    # to "unknown" rather than ever being omitted in practice.
    modeSummary: AnalysisRunModeSummary | None = None
    # The raw input URL strings this run was analyzed with (verbatim
    # from the original /analyze request's `urls`, via
    # analysis_runs.input_snapshot — see
    # services/analysis_history_repository.py's _extract_source_urls()).
    # Added for fix/history-domain-search as a domain-search fallback,
    # since `canonicalDomain` above is never actually populated by
    # save_analysis_history() today. Defaults to `[]`, never omitted,
    # so an older saved run with no `urls` in its input_snapshot (or no
    # input_snapshot at all) still round-trips cleanly.
    sourceUrls: list[str] = []
    # Whether this run has been marked important (analysis_runs.is_important,
    # backend/migrations/004_add_is_important_to_analysis_runs.sql — see
    # docs/38_history_marking_design.md 案A). Defaults to False so a run
    # read before this migration is applied (or any future legacy row)
    # still round-trips cleanly rather than raising.
    isImportant: bool = False
    # Whether this run has been marked a favorite
    # (analysis_runs.is_favorite, backend/migrations/
    # 007_add_is_favorite_to_analysis_runs.sql) — independent of
    # isImportant above (feature/history-favorite-flag). Defaults to
    # False for the same "migration not yet applied / legacy row"
    # reason as isImportant.
    isFavorite: bool = False
    # Every tag currently attached to this run (feature/history-tags-
    # categories) — defaults to `[]`, never omitted, same "legacy row
    # / migration not yet applied" reasoning as sourceUrls above.
    tags: list[TagItem] = []
    # This run's category, or None for "未分類" (including a legacy
    # row from before migration 008, or one whose category was
    # deleted — ON DELETE SET NULL already makes those indistinguishable
    # at the DB level, which is the intended behavior).
    category: CategoryItem | None = None


class AnalysisRunListResponse(BaseModel):
    items: list[AnalysisRunListItem]
    limit: int
    offset: int
    # Total matching row count across all pages. Always None in this
    # initial implementation — see
    # docs/20_analysis_history_read_api_design.md "13. 初期実装でやる
    # こと・やらないこと" ("total countの正確な実装" is out of scope).
    total: int | None = None


class AnalysisRunBrand(BaseModel):
    id: str
    name: str
    canonicalDomain: str | None


class AnalysisRunInfo(BaseModel):
    status: str
    inputSnapshot: dict[str, object]
    sourceSummary: dict[str, object] | None
    startedAt: str | None
    completedAt: str | None


class AnalysisRunDetailResponse(BaseModel):
    """GET /analysis-runs/{id} — see
    docs/20_analysis_history_read_api_design.md "6. GET
    /analysis-runs/{id} の設計案". Unlike AnalysisRunListItem, `result`
    holds the full stored analysis_results.result_json (the complete
    /analyze response as it was at save time) — kept as a loose
    dict[str, object] rather than AnalysisResult, since a saved row's
    shape reflects whatever AnalysisResult looked like when it was
    written, not necessarily the current one.
    """

    id: str
    brand: AnalysisRunBrand
    run: AnalysisRunInfo
    result: dict[str, object]
    meta: dict[str, object] | None
    # Same field/default as AnalysisRunListItem.isImportant above — see
    # that field's docstring and docs/38_history_marking_design.md.
    isImportant: bool = False
    # Same field/default as AnalysisRunListItem.isFavorite above
    # (feature/history-favorite-flag).
    isFavorite: bool = False
    # Exposes `analysis_runs.project_id` to a caller who has, by
    # definition, already passed this same run's access check (JWT
    # mode: can_user_access_analysis_run(); history_token mode:
    # unrestricted) to see this response at all — so this is not a new
    # information leak, only a convenience. Added for
    # feature/async-job-failure-display-and-retry: the frontend's
    # "re-run this analysis" action needs the original project id to
    # submit POST /analysis-jobs against (that endpoint still performs
    # its own full can_user_access_project() check independently —
    # this field is never treated as an authorization grant by itself,
    # only as "which project to ask the real check about"). `None` for
    # a legacy run saved before 002_add_organizations_projects.sql.
    projectId: str | None = None
    # Same field/default as AnalysisRunListItem.tags/category above
    # (feature/history-tags-categories).
    tags: list[TagItem] = []
    category: CategoryItem | None = None


class AnalysisRunImportantRequest(BaseModel):
    """PATCH /analysis-runs/{id}/important request body — see
    docs/38_history_marking_design.md "7. API設計案"."""

    isImportant: bool


class AnalysisRunImportantResponse(BaseModel):
    """PATCH /analysis-runs/{id}/important response — see
    docs/38_history_marking_design.md "7. API設計案". Mirrors
    GeminiRerunResponse's convention of echoing back the id alongside
    the field that was changed."""

    analysisRunId: str
    isImportant: bool


class AnalysisRunFavoriteRequest(BaseModel):
    """PATCH /analysis-runs/{id}/favorite request body
    (feature/history-favorite-flag) — mirrors
    AnalysisRunImportantRequest above exactly; the favorite flag is
    stored/toggled entirely independently of isImportant."""

    isFavorite: bool


class AnalysisRunFavoriteResponse(BaseModel):
    """PATCH /analysis-runs/{id}/favorite response
    (feature/history-favorite-flag) — mirrors
    AnalysisRunImportantResponse above exactly."""

    analysisRunId: str
    isFavorite: bool


class GeminiRerunResponse(BaseModel):
    """POST /analysis-runs/{id}/rerun/gemini — see
    services/gemini_rerun.py. `result` holds the updated, full
    result_json (same loose dict[str, object] shape as
    AnalysisRunDetailResponse.result above, for the same reason: a
    saved row's shape reflects whatever AnalysisResult looked like when
    it was written). A non-2xx response (see main.py) means nothing was
    updated — the previously saved result is unchanged.
    """

    updated: bool
    analysisRunId: str
    result: dict[str, object]


class WebAiGapAiComparisonResponse(BaseModel):
    """POST /analysis-runs/{id}/web-ai-gap/ai-comparison — see
    services/ai_gap_comparison.py. Unlike GeminiRerunResponse above,
    this returns only the newly generated comparison (not the full
    result), since the caller (history detail page) only needs to
    update its own `webAiGapAiComparison` slot — see
    docs/39_ai_gap_comparison_design.md "5. 出力形式設計". A non-2xx
    response (see main.py) means nothing was generated or saved — the
    existing rule-based `webAiGap` and any previously generated
    `webAiGapAiComparison` are both unchanged.
    """

    analysisRunId: str
    webAiGapAiComparison: WebAiGapAiComparison


class AnalysisRunComparisonRunSummary(BaseModel):
    """One side (`current`/`previous`) of GET
    /analysis-runs/{id}/comparison — see
    docs/25_analysis_history_comparison_design.md "8. API設計案".
    `visibilityScore` is None when the saved result is missing or
    doesn't have the expected `summary.visibilityScore` shape (see
    services/analysis_history_comparison.py)."""

    id: str
    startedAt: str | None
    visibilityScore: int | None


class AnalysisRunComparisonVisibilityScoreDiff(BaseModel):
    current: int | None
    previous: int | None
    delta: int | None


class CooccurrenceComparisonNewTerm(BaseModel):
    term: str
    rank: int
    score: int


class CooccurrenceComparisonRemovedTerm(BaseModel):
    term: str
    rank: int
    score: int


class CooccurrenceComparisonChangedTerm(BaseModel):
    """`rankDelta`/`scoreDelta` are current-minus-previous — a negative
    `rankDelta` means the term's rank *improved* (moved to a
    lower/better rank number), since rank 1 outranks rank 5."""

    term: str
    currentRank: int
    previousRank: int
    rankDelta: int
    currentScore: int
    previousScore: int
    scoreDelta: int


class AnalysisRunComparisonCooccurrenceDiff(BaseModel):
    topN: int
    newTerms: list[CooccurrenceComparisonNewTerm]
    removedTerms: list[CooccurrenceComparisonRemovedTerm]
    changedTerms: list[CooccurrenceComparisonChangedTerm]


class AnalysisRunComparisonImprovementsDiff(BaseModel):
    currentCount: int
    previousCount: int
    delta: int


class AnalysisRunComparisonDiff(BaseModel):
    visibilityScore: AnalysisRunComparisonVisibilityScoreDiff
    cooccurrence: AnalysisRunComparisonCooccurrenceDiff
    improvements: AnalysisRunComparisonImprovementsDiff


class AnalysisRunComparisonResponse(BaseModel):
    """GET /analysis-runs/{id}/comparison — see
    docs/25_analysis_history_comparison_design.md. `previous`/`diff`
    are both None when the same brand has no earlier run yet; in that
    case `warnings` explains why (see
    services/analysis_history_comparison.py's
    INSUFFICIENT_HISTORY_WARNING)."""

    current: AnalysisRunComparisonRunSummary
    previous: AnalysisRunComparisonRunSummary | None
    diff: AnalysisRunComparisonDiff | None
    warnings: list[str]


# --- Async analysis jobs, Phase 1 only (POST /analysis-jobs, GET
# /analysis-jobs/{id}, GET /analysis-jobs/{id}/result) — see
# docs/40_async_analysis_jobs_design.md. Phase 1 only ever creates rows
# with status="queued"; no worker exists yet to advance them, so these
# models' other status values ("running"/"completed"/"partial"/
# "failed") are defined now for forward compatibility with Phase 2 but
# are never produced by this phase's own code paths.


class AnalysisJobCreateRequest(BaseModel):
    """POST /analysis-jobs body. Mirrors AnalyzeRequest's analysis
    input fields exactly (brandName/documents/urls/four provider
    modes/commonCrawlDomain) plus two fields AnalyzeRequest has no
    concept of: `projectId` (which project this job belongs to — every
    job is authorized against this, see
    docs/40_async_analysis_jobs_design.md "8.1") and `idempotencyKey`
    (the client-generated key for this one "start analysis" operation,
    see docs/40 "10.1"). Both are required — unlike AnalyzeRequest's
    unauthenticated POST /analyze, a job always has a known caller and
    a known idempotency scope.
    """

    projectId: str
    idempotencyKey: str
    brandName: str | None = None
    documents: list[str] | None = None
    urls: list[str] | None = None
    aiOverviewMode: AiOverviewProviderMode | None = None
    chatgptMode: ChatGptProviderMode | None = None
    claudeMode: ClaudeProviderMode | None = None
    geminiMode: GeminiProviderMode | None = None
    commonCrawlMode: CommonCrawlProviderMode | None = None
    commonCrawlDomain: str | None = None


class AnalysisJobAcceptedResponse(BaseModel):
    """202 Accepted body for a newly created (or idempotently reused)
    job. `status` can be any job status, not only "queued" — an
    idempotency-key replay of an already-finished job (Phase 2+) still
    returns 202 with that job's current status rather than re-running
    anything, see docs/40_async_analysis_jobs_design.md "10.2"."""

    analysisRunId: str
    status: str


class AnalysisJobStatusResponse(BaseModel):
    """GET /analysis-jobs/{id}. Deliberately excludes result_json/
    meta_json — mirrors list_analysis_runs()'s existing "never includes
    result_json" discipline (services/analysis_history_repository.py)."""

    analysisRunId: str
    status: str
    startedAt: str | None
    completedAt: str | None
    errorMessage: str | None


class AnalysisJobResultResponse(BaseModel):
    """GET /analysis-jobs/{id}/result, for a job whose status is
    "completed"/"partial"/"failed" — see
    docs/40_async_analysis_jobs_design.md "13.2". `result`/`meta` are
    only ever populated for "completed"/"partial"; a "failed" job
    always has both None (there is nothing to show) with
    `errorMessage` set instead. A "queued"/"running" job never reaches
    this model at all — main.py returns a plain error_response() 409
    for those instead, since there is no result-shaped body to return
    yet."""

    analysisRunId: str
    status: str
    errorMessage: str | None = None
    result: dict | None = None
    meta: dict | None = None


# --- GET /me/projects — see docs/40_async_analysis_jobs_design.md
# "Phase 3". A minimal, read-only lookup so the frontend can learn
# which project(s) the current JWT-authenticated user may create a
# job under (POST /analysis-jobs requires an explicit `projectId` —
# see AnalysisJobCreateRequest above — and nothing else in this API
# previously told a caller which project id(s) they're even allowed to
# use). Returns only the ids of projects
# services.project_access.get_accessible_project_ids() already says
# this user belongs to — never any other user's or any other
# project's data.


class MeProjectItem(BaseModel):
    id: str


class MeProjectsResponse(BaseModel):
    projects: list[MeProjectItem]
