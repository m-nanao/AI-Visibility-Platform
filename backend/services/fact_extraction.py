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
    """The only source-of-truth check in this module: does
    `original_text[start:end]` equal `source_text`, exactly?

    - Rejects out-of-range/empty/reversed spans before slicing.
    - Uses Python string (Unicode code point) indices — see
      FactExtractedClaim's own docstring on the UTF-16 caveat for a
      future frontend.
    - Never falls back to `.find()`/similarity matching: when the same
      `source_text` appears multiple times in `original_text`, this
      function only ever checks whether the ONE claimed span matches —
      it does not search for or care about other occurrences, which is
      exactly how ambiguity is avoided (the candidate must commit to a
      specific span, not merely assert the quote exists somewhere).
    """
    if start < 0 or end <= start or end > len(original_text):
        return False
    return original_text[start:end] == source_text


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
    """
    if candidate.answerState == "not_mentioned":
        return None

    if (
        candidate.sourceText is None
        or candidate.sourceStartIndex is None
        or candidate.sourceEndIndex is None
    ):
        return None

    if not verify_source_span(
        original_text, candidate.sourceText, candidate.sourceStartIndex, candidate.sourceEndIndex
    ):
        return None

    try:
        return FactExtractedClaim(
            claimId=claim_id,
            brandName=brand_name,
            claimCategory=candidate.claimCategory,
            claimNature=candidate.claimNature,
            answerState=candidate.answerState,
            claimText=candidate.claimText,
            sourceText=candidate.sourceText,
            sourceStartIndex=candidate.sourceStartIndex,
            sourceEndIndex=candidate.sourceEndIndex,
            sourceModel=source_model,
            extractionModel=extraction_model,
            observationMethod=observation_method,
            sourcePlatform=source_platform,
            uncertaintyMarkers=candidate.uncertaintyMarkers,
        )
    except ValidationError:
        return None


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
    if candidate.answerState != "not_mentioned":
        return None
    if (
        candidate.sourceText is not None
        or candidate.sourceStartIndex is not None
        or candidate.sourceEndIndex is not None
    ):
        return None

    try:
        return FactCategoryNotMentioned(
            claimCategory=candidate.claimCategory,
            brandName=brand_name,
            sourceModel=source_model,
            observationMethod=observation_method,
            sourcePlatform=source_platform,
        )
    except ValidationError:
        return None


@dataclass(frozen=True)
class ClaimBatchResult:
    claims: list[FactExtractedClaim]
    notMentionedCategories: list[FactCategoryNotMentioned]
    rejectedCount: int
    truncated: bool


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
    truncated = len(candidates) > MAX_FACT_CLAIMS_PER_CARD
    limited = candidates[:MAX_FACT_CLAIMS_PER_CARD]

    claims: list[FactExtractedClaim] = []
    not_mentioned: list[FactCategoryNotMentioned] = []
    rejected_count = 0
    for candidate in limited:
        if candidate.answerState == "not_mentioned":
            category_state = build_category_not_mentioned(
                candidate,
                source_platform=source_platform,
                observation_method=observation_method,
                source_model=source_model,
                brand_name=brand_name,
            )
            if category_state is None:
                rejected_count += 1
            else:
                not_mentioned.append(category_state)
            continue

        claim = verify_and_build_claim(
            candidate,
            original_text=original_text,
            source_platform=source_platform,
            observation_method=observation_method,
            source_model=source_model,
            extraction_model=extraction_model,
            brand_name=brand_name,
        )
        if claim is None:
            rejected_count += 1
        else:
            claims.append(claim)

    return ClaimBatchResult(
        claims=claims,
        notMentionedCategories=not_mentioned,
        rejectedCount=rejected_count,
        truncated=truncated,
    )
