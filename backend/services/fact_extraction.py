"""Task 6-D-5C-1 (feature/fact-extraction-data-model): verification-
only infrastructure for decomposing an AI answer into per-claim
factual assertions about the subject brand.

**No LLM extraction call is made anywhere in this module.** This file
provides three things a future extraction client (Task 6-D-5C-2) will
need, none of which require calling any API:

1. `select_fact_extraction_eligible_cards()` / `classify_eligible_card()`
   — an explicit allowlist of (platform, observationMethod)
   combinations that may ever be fed into fact extraction. Gemini's
   Google-Search-grounding supplement
   (services/gemini_websearch_provider.py) is deliberately excluded —
   see the module-level `_ALLOWED_OBSERVATION_METHODS_BY_LABEL` comment
   for why checking `observationMethod` alone is not enough to exclude
   it (it shares the "websearch_supplement" value with ChatGPT's and
   Claude's own, legitimately-eligible supplement cards).
2. `resolve_original_text()` — decides which stored string a claim's
   `sourceText` must be verified against (`fullSummary` when present,
   `summary` as a flagged fallback otherwise — see the task's item 3).
3. `verify_and_build_claim()` / `build_category_not_mentioned()` /
   `verify_and_build_claims()` — the only way to turn an untrusted
   `models.RawFactClaimCandidate` (the shape a future LLM extraction
   call would produce) into either a trusted, source-grounded
   `models.FactExtractedClaim`, or (when the candidate's answerState
   is "not_mentioned") a trusted `models.FactCategoryNotMentioned` —
   see that model's own docstring for why the two are kept separate.
   Verification for a grounded claim is a single rule: the claimed
   span must be an *exact* substring match against the real original
   text at the claimed Python-string indices. No fuzzy/similarity
   matching, no trusting the model's own span without checking it, no
   inventing a span for a "not mentioned" category. A candidate that
   fails is dropped, never silently "fixed" or guessed into shape.

Deliberately a separate module (not inlined into main.py or
web_ai_gap.py) — this subsystem has its own, independent lifecycle
(Task 6-D-5C-2/6-D-5C-3 will extend it) and no part of the existing
`/analyze` pipeline calls anything here yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from models import (
    AIOverviewComparisonItem,
    FactCategoryNotMentioned,
    FactExtractedClaim,
    FactSourcePlatform,
    MAX_FACT_CLAIMS_PER_CARD,
    MAX_FACT_ORIGINAL_TEXT_CHARS,
    ObservationMethod,
    RawFactClaimCandidate,
)
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.chatgpt_websearch_provider import CHATGPT_WEBSEARCH_PLATFORM_LABEL
from services.claude_provider import CLAUDE_PLATFORM_LABEL
from services.claude_websearch_provider import CLAUDE_WEBSEARCH_PLATFORM_LABEL
from services.gemini_external_document_provider import (
    GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL,
)
from services.gemini_provider import GEMINI_PLATFORM_LABEL

# Deliberately NOT importing
# services.gemini_websearch_provider.GEMINI_WEBSEARCH_PLATFORM_LABEL —
# Gemini's Google-Search-grounding supplement card must never become
# eligible for fact extraction (see module docstring item 1 and
# docs/07_decisions.md's Grounding-ToS NO-GO finding, Task 6-D-4B-3A).
# Its absence from every dict below is what keeps it excluded; a
# future edit that adds it back in must do so deliberately, not by
# accident of some generic "all Gemini platform labels" rule.

# platform (AIOverviewComparisonItem.platform, a raw display string) ->
# the classified FactSourcePlatform it represents, IF eligible at all.
# A platform label absent from this dict is never eligible, regardless
# of observationMethod — this is the allowlist's first gate.
_ELIGIBLE_PLATFORM_LABELS: dict[str, FactSourcePlatform] = {
    CHATGPT_PLATFORM_LABEL: "chatgpt",
    CHATGPT_WEBSEARCH_PLATFORM_LABEL: "chatgpt",
    CLAUDE_PLATFORM_LABEL: "claude",
    CLAUDE_WEBSEARCH_PLATFORM_LABEL: "claude",
    GEMINI_PLATFORM_LABEL: "gemini",
    GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL: "gemini",
}

# platform -> the set of observationMethod values that are actually
# eligible for THAT platform label. This is the allowlist's second
# gate, and the reason a single "is this platform label known" check
# is not sufficient: GEMINI_WEBSEARCH_PLATFORM_LABEL ("Gemini (Google
# API, Web検索補完)") is a *different* label from
# GEMINI_PLATFORM_LABEL/GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL and is
# simply never a key here, so it is excluded by gate one already — but
# the per-label observationMethod set below is kept anyway as defense
# in depth, and because it is what actually distinguishes a no-search
# ChatGPT/Claude/Gemini card (observationMethod None or
# "single_call_no_search") from that SAME platform label's supplement
# variant would-be mixup. `None` is included for the three no-search
# labels because older saved cards/history predate the
# observationMethod field entirely (see ObservationMethod's own
# docstring in models.py) and must still be treated as eligible
# no-search cards, not silently excluded just for predating the field.
_ALLOWED_OBSERVATION_METHODS_BY_LABEL: dict[str, frozenset[ObservationMethod | None]] = {
    CHATGPT_PLATFORM_LABEL: frozenset({None, "single_call_no_search"}),
    CHATGPT_WEBSEARCH_PLATFORM_LABEL: frozenset({"websearch_supplement"}),
    CLAUDE_PLATFORM_LABEL: frozenset({None, "single_call_no_search"}),
    CLAUDE_WEBSEARCH_PLATFORM_LABEL: frozenset({"websearch_supplement"}),
    GEMINI_PLATFORM_LABEL: frozenset({None, "single_call_no_search"}),
    GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL: frozenset({"external_document_supplement"}),
}


def classify_eligible_card(
    platform: str, observation_method: ObservationMethod | None
) -> FactSourcePlatform | None:
    """Returns the classified `FactSourcePlatform` if `(platform,
    observation_method)` is on the allowlist, else `None`.

    Deliberately an allowlist, not a blocklist: any platform label
    this function doesn't recognize at all — including any future
    label, and including Gemini's own Google-Search-grounding
    supplement label — returns `None` by default. A new observation
    method/provider added to this codebase later never becomes
    eligible automatically; someone must deliberately add it here.
    """
    allowed_methods = _ALLOWED_OBSERVATION_METHODS_BY_LABEL.get(platform)
    if allowed_methods is None:
        return None
    if observation_method not in allowed_methods:
        return None
    return _ELIGIBLE_PLATFORM_LABELS[platform]


def select_fact_extraction_eligible_cards(
    items: list[AIOverviewComparisonItem],
) -> list[tuple[AIOverviewComparisonItem, FactSourcePlatform]]:
    """Filters `items` (an AnalysisResult.aiOverviewComparison list)
    down to only the cards eligible for fact extraction, paired with
    their classified `FactSourcePlatform`. Order is preserved; AI
    Overview/DataForSEO/mock cards and Gemini's Google-Search-
    grounding supplement card are never included.
    """
    eligible: list[tuple[AIOverviewComparisonItem, FactSourcePlatform]] = []
    for item in items:
        source_platform = classify_eligible_card(item.platform, item.observationMethod)
        if source_platform is not None:
            eligible.append((item, source_platform))
    return eligible


@dataclass(frozen=True)
class OriginalTextResolution:
    """The text a claim's sourceText must be verified against, plus
    whether it came from the full answer or the shortened card
    `summary` (see resolve_original_text()). `text` is already capped
    to MAX_FACT_ORIGINAL_TEXT_CHARS — see that function's own
    docstring for why a truncated original text is still used as-is
    rather than rejected outright.
    """

    text: str
    isFallbackSummary: bool
    isTruncated: bool


def resolve_original_text(item: AIOverviewComparisonItem) -> OriginalTextResolution:
    """Picks the original-answer text a claim must be verified
    against for one card: `item.fullSummary` when it is a non-blank
    string, otherwise `item.summary` (the task's item 3: "fullSummary
    が存在しない場合のみ、既存のsummaryへのフォールバックを検討する。
    ただし、カード用に短縮されたsummaryから抽出したことを明示する。").

    Capped to MAX_FACT_ORIGINAL_TEXT_CHARS from the end truncated off
    (never the start — a claim's span indices are always relative to
    the text actually used for verification, so truncating the same
    text consistently keeps indices meaningful; it does not retroactively
    make an already-verified claim's indices wrong, it only means any
    sourceText appearing past the cap can never be verified — which is
    the intended, safe failure mode for an abnormally long answer, not
    a bug).
    """
    if item.fullSummary is not None and item.fullSummary.strip():
        text = item.fullSummary
        is_fallback = False
    else:
        text = item.summary
        is_fallback = True

    is_truncated = len(text) > MAX_FACT_ORIGINAL_TEXT_CHARS
    if is_truncated:
        text = text[:MAX_FACT_ORIGINAL_TEXT_CHARS]
    return OriginalTextResolution(text=text, isFallbackSummary=is_fallback, isTruncated=is_truncated)


def verify_source_span(original_text: str, source_text: str, start: int, end: int) -> bool:
    """The only strict, claimed-span check in this module: does
    `original_text[start:end]` equal `source_text`, exactly?

    - Rejects out-of-range/empty/reversed spans before slicing.
    - Uses Python string (Unicode code point) indices — see
      FactExtractedClaim's own docstring on the UTF-16 caveat for a
      future frontend.
    - Never falls back to `.find()`/similarity matching: when the same
      `source_text` appears multiple times in `original_text`, this
      function only ever checks whether the ONE claimed span matches —
      it does not search for or care about other occurrences. Kept
      deliberately strict and unchanged (Task 6-D-5C-3C did not modify
      this function) so every existing caller/test of this exact
      function keeps its current meaning; see
      `_find_source_text_occurrences()`/`verify_and_build_claim()` for
      where Task 6-D-5C-3C's new "unique-occurrence correction"
      fallback lives instead.
    """
    if start < 0 or end <= start or end > len(original_text):
        return False
    return original_text[start:end] == source_text


# Task 6-D-5C-3C: Task 6-D-5C-3B-4's real-API run rejected 4 of 5
# candidates, and investigation (see this task's own report) found
# that Claude's own `sourceStartIndex`/`sourceEndIndex` are frequently
# off by a small amount even when `sourceText` itself is a genuine,
# unique verbatim quote from the original text — expected, since
# SYSTEM_PROMPT itself tells Claude "位置がずれていても構わない...正確
# 性はこちら側で別途検証します" (services/fact_extraction_client.py).
# `verify_source_span()` alone can only ever reject such a candidate,
# never correct it.
#
# This finds every exact, non-overlapping-start occurrence of
# `source_text` in `original_text` via `str.find()` — the same
# operation `verify_source_span()`'s own exact-match check implies,
# just enumerated instead of checked at one claimed position. An
# occurrence here is, by construction, always a real verbatim
# substring: this function can never invent, fuzzy-match, or
# paraphrase a span, only locate ones that already exist character-
# for-character.
def _find_source_text_occurrences(original_text: str, source_text: str) -> list[tuple[int, int]]:
    occurrences: list[tuple[int, int]] = []
    if not source_text:
        return occurrences
    search_from = 0
    while True:
        index = original_text.find(source_text, search_from)
        if index == -1:
            break
        occurrences.append((index, index + len(source_text)))
        search_from = index + 1  # allows overlapping occurrences to all be found
    return occurrences


REASON_MISSING_SOURCE_SPAN = "missing_source_span"
REASON_SOURCE_TEXT_NOT_FOUND = "source_text_not_found"
# Task 6-D-5C-3C's own hard requirement: "複数箇所に同じ文字列がある場合、
# 曖昧な位置を誤採用しない" — when `source_text` genuinely occurs 2+
# times and the model's claimed span doesn't exactly match any of them,
# this module refuses to guess which occurrence was meant, exactly like
# it already refuses to guess for a span that doesn't match at all.
REASON_SOURCE_TEXT_AMBIGUOUS = "source_text_ambiguous_multiple_occurrences"
REASON_CLAIM_VALIDATION_ERROR = "claim_validation_error"
REASON_NOT_MENTIONED_WITH_LEFTOVER_SPAN = "not_mentioned_candidate_has_leftover_span"
REASON_NOT_MENTIONED_VALIDATION_ERROR = "not_mentioned_validation_error"
REASON_NOT_A_GROUNDED_CANDIDATE = "answer_state_is_not_mentioned_not_grounded"
REASON_NOT_A_NOT_MENTIONED_CANDIDATE = "answer_state_is_grounded_not_not_mentioned"
REASON_MAX_CLAIMS_PER_CARD_CAP_EXCEEDED = "max_claims_per_card_cap_exceeded"


@dataclass(frozen=True)
class _SpanResolution:
    """Internal-only outcome of resolving one grounded candidate's
    span against `original_text` — never exposed outside this module
    as a return value in its own right; see `ClaimVerificationDiagnostic`
    for the diagnostic-only, public-facing shape derived from this.
    """

    start: int | None
    end: int | None
    corrected: bool
    occurrence_count: int
    rejection_reason: str | None


def _resolve_grounded_span(
    original_text: str, source_text: str, claimed_start: int, claimed_end: int
) -> _SpanResolution:
    """Resolves one grounded (asserted/explicit_unknown/explicit_denial)
    candidate's span, preferring the model's own claimed indices and
    falling back to a unique-occurrence correction only when those
    indices don't match. Three outcomes:

    1. The claimed span matches exactly — used as-is, `corrected=False`
       (today's existing, unchanged behavior for every candidate whose
       own indices happen to be right).
    2. The claimed span doesn't match, but `source_text` occurs exactly
       once elsewhere in `original_text` — that one real occurrence's
       own indices are used instead, `corrected=True`. Still only ever
       an exact verbatim substring; nothing is invented.
    3. `source_text` occurs zero times, or 2+ times with none matching
       the claimed span — rejected (`start`/`end` are `None`), since
       guessing which occurrence was meant would be exactly the
       "ambiguous position" risk this task's own requirements forbid.
    """
    if verify_source_span(original_text, source_text, claimed_start, claimed_end):
        return _SpanResolution(
            start=claimed_start,
            end=claimed_end,
            corrected=False,
            occurrence_count=1,
            rejection_reason=None,
        )

    occurrences = _find_source_text_occurrences(original_text, source_text)
    if len(occurrences) == 1:
        start, end = occurrences[0]
        return _SpanResolution(
            start=start, end=end, corrected=True, occurrence_count=1, rejection_reason=None
        )
    if len(occurrences) == 0:
        return _SpanResolution(
            start=None,
            end=None,
            corrected=False,
            occurrence_count=0,
            rejection_reason=REASON_SOURCE_TEXT_NOT_FOUND,
        )
    return _SpanResolution(
        start=None,
        end=None,
        corrected=False,
        occurrence_count=len(occurrences),
        rejection_reason=REASON_SOURCE_TEXT_AMBIGUOUS,
    )


@dataclass(frozen=True)
class ClaimVerificationDiagnostic:
    """Task 6-D-5C-3C: a diagnostic-only record of how one candidate
    was verified — never persisted to the database, never attached to
    `FactExtractedClaim`/`FactCategoryNotMentioned`/`AnalysisResult`,
    and consumed only by
    `backend/scripts/fact_extraction_local_verification.py` (a future
    real-API run can now explain its own rejectedCount without a
    second API call). `sourceTextOccurrenceCount` is `None` when no
    occurrence search was ever performed (e.g. the candidate was
    missing its span entirely, or was a `not_mentioned` candidate).
    """

    candidateIndex: int
    claimCategory: str
    answerState: str
    accepted: bool
    rejectionReason: str | None
    sourceTextOccurrenceCount: int | None
    spanWasCorrected: bool
    # Task 6-D-5C-3C item 6 (output-token investigation): lengths only,
    # never the content — safe to log/report for every candidate
    # (accepted or rejected) so a future real-API run's output-token
    # usage can be explained (e.g. "most output tokens went into 4
    # candidates' sourceText, each quoting the same ~50-char sentence")
    # without a second API call and without ever re-exposing the
    # original AI answer's text.
    claimTextLength: int
    sourceTextLength: int | None


def _verify_and_build_claim_core(
    candidate: RawFactClaimCandidate,
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None,
    claim_id: str | None,
    candidate_index: int,
) -> tuple[FactExtractedClaim | None, ClaimVerificationDiagnostic]:
    """Shared implementation behind `verify_and_build_claim()` (which
    discards the diagnostic) and
    `verify_and_build_claim_with_diagnostics()` (which returns it) —
    see either's own docstring. Kept as one function so the two can
    never drift into checking different things.
    """

    def _rejected(reason: str, *, occurrence_count: int | None = None) -> ClaimVerificationDiagnostic:
        return ClaimVerificationDiagnostic(
            candidateIndex=candidate_index,
            claimCategory=candidate.claimCategory,
            answerState=candidate.answerState,
            accepted=False,
            rejectionReason=reason,
            sourceTextOccurrenceCount=occurrence_count,
            spanWasCorrected=False,
            claimTextLength=len(candidate.claimText),
            sourceTextLength=len(candidate.sourceText) if candidate.sourceText is not None else None,
        )

    if candidate.answerState == "not_mentioned":
        return None, _rejected(REASON_NOT_A_GROUNDED_CANDIDATE)

    if (
        candidate.sourceText is None
        or candidate.sourceStartIndex is None
        or candidate.sourceEndIndex is None
    ):
        return None, _rejected(REASON_MISSING_SOURCE_SPAN)

    resolution = _resolve_grounded_span(
        original_text, candidate.sourceText, candidate.sourceStartIndex, candidate.sourceEndIndex
    )
    if resolution.start is None or resolution.end is None:
        assert resolution.rejection_reason is not None
        return None, _rejected(resolution.rejection_reason, occurrence_count=resolution.occurrence_count)

    try:
        claim = FactExtractedClaim(
            claimId=claim_id,
            brandName=brand_name,
            claimCategory=candidate.claimCategory,
            claimNature=candidate.claimNature,
            answerState=candidate.answerState,
            claimText=candidate.claimText,
            sourceText=candidate.sourceText,
            sourceStartIndex=resolution.start,
            sourceEndIndex=resolution.end,
            sourceModel=source_model,
            extractionModel=extraction_model,
            observationMethod=observation_method,
            sourcePlatform=source_platform,
            uncertaintyMarkers=candidate.uncertaintyMarkers,
        )
    except ValidationError:
        return None, _rejected(REASON_CLAIM_VALIDATION_ERROR, occurrence_count=resolution.occurrence_count)

    diagnostic = ClaimVerificationDiagnostic(
        candidateIndex=candidate_index,
        claimCategory=candidate.claimCategory,
        answerState=candidate.answerState,
        accepted=True,
        rejectionReason=None,
        sourceTextOccurrenceCount=resolution.occurrence_count,
        spanWasCorrected=resolution.corrected,
        claimTextLength=len(candidate.claimText),
        sourceTextLength=len(candidate.sourceText) if candidate.sourceText is not None else None,
    )
    return claim, diagnostic


def verify_and_build_claim(
    candidate: RawFactClaimCandidate,
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None = None,
    claim_id: str | None = None,
) -> FactExtractedClaim | None:
    """Verifies one untrusted `candidate` against `original_text` and,
    only if it passes, returns a trusted `FactExtractedClaim`.
    Returns `None` on any verification failure — never raises for a
    "plausible but wrong" candidate (a bad category/nature/state/
    length was already rejected earlier, at `RawFactClaimCandidate`
    construction time, by Pydantic).

    `source_platform`/`observation_method`/`source_model`/
    `extraction_model`/`brand_name` are all supplied by the trusted
    calling context (the orchestrator that already knows which card
    this candidate came from) — never read off `candidate` itself, so
    a malicious/malformed extraction response can never claim to have
    come from a different platform or model than it actually did.

    Returns `None` (never raises, never builds anything) when
    `candidate.answerState == "not_mentioned"` — a `FactExtractedClaim`
    cannot represent that state at all (see its own docstring). Use
    `build_category_not_mentioned()` for that case instead.

    **Task 6-D-5C-3C**: the returned claim's `sourceStartIndex`/
    `sourceEndIndex` are not always `candidate`'s own claimed indices
    verbatim any more — see `_resolve_grounded_span()`'s own docstring
    for the unique-occurrence correction this function now applies
    before rejecting a candidate outright. `sourceText` itself is
    always still the model's own candidate string, always still an
    exact, verbatim substring of `original_text` either way.
    """
    claim, _diagnostic = _verify_and_build_claim_core(
        candidate,
        original_text=original_text,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        extraction_model=extraction_model,
        brand_name=brand_name,
        claim_id=claim_id,
        candidate_index=0,
    )
    return claim


def verify_and_build_claim_with_diagnostics(
    candidate: RawFactClaimCandidate,
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None = None,
    claim_id: str | None = None,
    candidate_index: int = 0,
) -> tuple[FactExtractedClaim | None, ClaimVerificationDiagnostic]:
    """Task 6-D-5C-3C: same verification as `verify_and_build_claim()`,
    plus the `ClaimVerificationDiagnostic` explaining the outcome —
    see that dataclass's own docstring. Diagnostic-only; never used by
    the production pipeline (services/fact_extraction_provider.py
    still calls the plain `verify_and_build_claims()` below, which
    discards diagnostics), only by
    backend/scripts/fact_extraction_local_verification.py.
    """
    return _verify_and_build_claim_core(
        candidate,
        original_text=original_text,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        extraction_model=extraction_model,
        brand_name=brand_name,
        claim_id=claim_id,
        candidate_index=candidate_index,
    )


def _build_category_not_mentioned_core(
    candidate: RawFactClaimCandidate,
    *,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    brand_name: str | None,
    candidate_index: int,
) -> tuple[FactCategoryNotMentioned | None, ClaimVerificationDiagnostic]:
    """Shared implementation behind `build_category_not_mentioned()`
    and `build_category_not_mentioned_with_diagnostics()` — see
    `_verify_and_build_claim_core()`'s own docstring for why this
    split exists.
    """

    def _rejected(reason: str) -> ClaimVerificationDiagnostic:
        return ClaimVerificationDiagnostic(
            candidateIndex=candidate_index,
            claimCategory=candidate.claimCategory,
            answerState=candidate.answerState,
            accepted=False,
            rejectionReason=reason,
            sourceTextOccurrenceCount=None,
            spanWasCorrected=False,
            claimTextLength=len(candidate.claimText),
            sourceTextLength=len(candidate.sourceText) if candidate.sourceText is not None else None,
        )

    if candidate.answerState != "not_mentioned":
        return None, _rejected(REASON_NOT_A_NOT_MENTIONED_CANDIDATE)
    if (
        candidate.sourceText is not None
        or candidate.sourceStartIndex is not None
        or candidate.sourceEndIndex is not None
    ):
        return None, _rejected(REASON_NOT_MENTIONED_WITH_LEFTOVER_SPAN)

    try:
        category_state = FactCategoryNotMentioned(
            claimCategory=candidate.claimCategory,
            brandName=brand_name,
            sourceModel=source_model,
            observationMethod=observation_method,
            sourcePlatform=source_platform,
        )
    except ValidationError:
        return None, _rejected(REASON_NOT_MENTIONED_VALIDATION_ERROR)

    diagnostic = ClaimVerificationDiagnostic(
        candidateIndex=candidate_index,
        claimCategory=candidate.claimCategory,
        answerState=candidate.answerState,
        accepted=True,
        rejectionReason=None,
        sourceTextOccurrenceCount=None,
        spanWasCorrected=False,
        claimTextLength=len(candidate.claimText),
        sourceTextLength=None,
    )
    return category_state, diagnostic


def build_category_not_mentioned(
    candidate: RawFactClaimCandidate,
    *,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    brand_name: str | None = None,
) -> FactCategoryNotMentioned | None:
    """The `not_mentioned` counterpart to verify_and_build_claim().
    Returns `None` (rejects the candidate outright) when
    `candidate.answerState != "not_mentioned"`, or when the candidate
    still carries a `sourceText`/span despite claiming `not_mentioned`
    — such a candidate is internally inconsistent and must never be
    silently "fixed" by dropping the extra fields; it is dropped
    entirely instead, same failure mode as a bad span in
    verify_and_build_claim().

    `FactCategoryNotMentioned` itself has no fields that could hold a
    fabricated sourceText/span at all, so this check exists purely to
    catch and reject a malformed candidate up front, not to sanitize
    one into shape.
    """
    category_state, _diagnostic = _build_category_not_mentioned_core(
        candidate,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        brand_name=brand_name,
        candidate_index=0,
    )
    return category_state


def build_category_not_mentioned_with_diagnostics(
    candidate: RawFactClaimCandidate,
    *,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    brand_name: str | None = None,
    candidate_index: int = 0,
) -> tuple[FactCategoryNotMentioned | None, ClaimVerificationDiagnostic]:
    """Task 6-D-5C-3C: diagnostic-returning counterpart to
    `build_category_not_mentioned()` — see
    `verify_and_build_claim_with_diagnostics()`'s own docstring for the
    same pattern applied to the grounded-claim path.
    """
    return _build_category_not_mentioned_core(
        candidate,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        brand_name=brand_name,
        candidate_index=candidate_index,
    )


@dataclass(frozen=True)
class ClaimBatchResult:
    claims: list[FactExtractedClaim]
    notMentionedCategories: list[FactCategoryNotMentioned]
    rejectedCount: int
    truncated: bool


def _verify_and_build_claims_core(
    candidates: list[RawFactClaimCandidate],
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None,
) -> tuple[ClaimBatchResult, list[ClaimVerificationDiagnostic]]:
    """Shared implementation behind `verify_and_build_claims()` (which
    discards the diagnostics list) and
    `verify_and_build_claims_with_diagnostics()` (which returns it) —
    see either's own docstring. `diagnostics` has exactly one entry
    per *input* candidate, in order, including the ones dropped by the
    `MAX_FACT_CLAIMS_PER_CARD` cap (so a diagnostic consumer can always
    explain every one of `len(candidates)` inputs, not just the ones
    actually considered).
    """
    truncated = len(candidates) > MAX_FACT_CLAIMS_PER_CARD
    limited = candidates[:MAX_FACT_CLAIMS_PER_CARD]

    claims: list[FactExtractedClaim] = []
    not_mentioned: list[FactCategoryNotMentioned] = []
    rejected_count = 0
    diagnostics: list[ClaimVerificationDiagnostic] = []
    for index, candidate in enumerate(limited):
        if candidate.answerState == "not_mentioned":
            category_state, diagnostic = _build_category_not_mentioned_core(
                candidate,
                source_platform=source_platform,
                observation_method=observation_method,
                source_model=source_model,
                brand_name=brand_name,
                candidate_index=index,
            )
            diagnostics.append(diagnostic)
            if category_state is None:
                rejected_count += 1
            else:
                not_mentioned.append(category_state)
            continue

        claim, diagnostic = _verify_and_build_claim_core(
            candidate,
            original_text=original_text,
            source_platform=source_platform,
            observation_method=observation_method,
            source_model=source_model,
            extraction_model=extraction_model,
            brand_name=brand_name,
            claim_id=None,
            candidate_index=index,
        )
        diagnostics.append(diagnostic)
        if claim is None:
            rejected_count += 1
        else:
            claims.append(claim)

    for index in range(len(limited), len(candidates)):
        candidate = candidates[index]
        diagnostics.append(
            ClaimVerificationDiagnostic(
                candidateIndex=index,
                claimCategory=candidate.claimCategory,
                answerState=candidate.answerState,
                accepted=False,
                rejectionReason=REASON_MAX_CLAIMS_PER_CARD_CAP_EXCEEDED,
                sourceTextOccurrenceCount=None,
                spanWasCorrected=False,
                claimTextLength=len(candidate.claimText),
                sourceTextLength=len(candidate.sourceText) if candidate.sourceText is not None else None,
            )
        )

    batch = ClaimBatchResult(
        claims=claims,
        notMentionedCategories=not_mentioned,
        rejectedCount=rejected_count,
        truncated=truncated,
    )
    return batch, diagnostics


def verify_and_build_claims(
    candidates: list[RawFactClaimCandidate],
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None = None,
) -> ClaimBatchResult:
    """Batch form of verify_and_build_claim()/build_category_not_mentioned()
    for one card's candidate claims — dispatches each candidate to
    whichever of the two applies based on its own `answerState`.
    Enforces MAX_FACT_CLAIMS_PER_CARD by taking only the first N
    candidates in order — `truncated` is True whenever `candidates`
    contained more than that many entries, regardless of how many of
    those extra entries would have passed verification anyway (the
    cap is on *candidates considered*, covering `claims` and
    `notMentionedCategories` together, not on verified output alone —
    so this is detectable even when every candidate beyond the cap
    would have failed verification too).
    """
    batch, _diagnostics = _verify_and_build_claims_core(
        candidates,
        original_text=original_text,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        extraction_model=extraction_model,
        brand_name=brand_name,
    )
    return batch


def verify_and_build_claims_with_diagnostics(
    candidates: list[RawFactClaimCandidate],
    *,
    original_text: str,
    source_platform: FactSourcePlatform,
    observation_method: ObservationMethod | None,
    source_model: str | None,
    extraction_model: str | None,
    brand_name: str | None = None,
) -> tuple[ClaimBatchResult, list[ClaimVerificationDiagnostic]]:
    """Task 6-D-5C-3C: same batch verification as
    `verify_and_build_claims()`, plus a `ClaimVerificationDiagnostic`
    per input candidate explaining exactly why each one was accepted
    or rejected — see that dataclass's own docstring. Built so a local
    verification run (backend/scripts/fact_extraction_local_verification.py)
    can report `rejectedCount`'s breakdown without a second API call
    and without ever logging the candidates' own `sourceText`/
    `claimText` content (the diagnostic carries only counts/category/
    booleans/reason codes).
    """
    return _verify_and_build_claims_core(
        candidates,
        original_text=original_text,
        source_platform=source_platform,
        observation_method=observation_method,
        source_model=source_model,
        extraction_model=extraction_model,
        brand_name=brand_name,
    )
