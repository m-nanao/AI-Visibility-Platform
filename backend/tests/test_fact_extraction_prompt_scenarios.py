"""Task 6-D-5C-2's own required test patterns (item 5): confirms the
full parse -> verify -> build pipeline (services/fact_extraction_client.py's
JSON extraction + services/fact_extraction.py's span verification, both
already independently tested elsewhere) correctly distinguishes each of
these linguistic patterns end-to-end, using mock Claude JSON output —
never a real API call.

Each test simulates "what Claude's JSON output would look like" for one
pattern and runs it through the exact same functions
services/fact_extraction_provider.py uses, proving the pipeline
preserves the distinction rather than collapsing it.
"""

import json

import services.fact_extraction_client as fec
from models import RawFactClaimCandidate
from services.fact_extraction import verify_and_build_claim


def _claim_item(**fields) -> dict:
    base = {"uncertaintyMarkers": []}
    base.update(fields)
    return base


def _parse_and_verify(original_text: str, claim_item: dict):
    """Round-trips one claim item through the client's JSON parser and
    the fact_extraction module's verification, exactly like
    services/fact_extraction_provider.py does for a real response."""
    raw_text = json.dumps({"claims": [claim_item]})
    parsed, parse_reason = fec.parse_fact_extraction_json(raw_text)
    assert parse_reason is None
    candidates, malformed_count = fec._build_raw_candidates(parsed)
    assert malformed_count == 0
    assert len(candidates) == 1
    candidate = candidates[0]

    if candidate.answerState == "not_mentioned":
        return candidate, None

    claim = verify_and_build_claim(
        candidate,
        original_text=original_text,
        source_platform="chatgpt",
        observation_method=None,
        source_model="gpt-5",
        extraction_model="claude-sonnet-5-5",
    )
    return candidate, claim


# --- 「代表者はA氏ではない」(explicit denial, with negation in Japanese) --


def test_explicit_denial_phrasing_is_classified_as_denial_not_unknown():
    original_text = "代表者はA氏ではありません。"
    item = _claim_item(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="explicit_denial",
        claimText="代表者はA氏ではない",
        sourceText="代表者はA氏ではありません",
        sourceStartIndex=0,
        sourceEndIndex=13,
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert candidate.answerState == "explicit_denial"
    assert claim is not None
    assert claim.answerState == "explicit_denial"


# --- 「代表者は不明」(explicit unknown — distinct from denial) ------------


def test_explicit_unknown_phrasing_is_classified_as_unknown_not_denial():
    original_text = "代表者は不明です。"
    item = _claim_item(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="explicit_unknown",
        claimText="代表者は不明",
        sourceText="代表者は不明です",
        sourceStartIndex=0,
        sourceEndIndex=8,
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert candidate.answerState == "explicit_unknown"
    assert claim is not None
    assert claim.answerState == "explicit_unknown"
    assert claim.answerState != "explicit_denial"


# --- 「代表者はいない」(denial of existence) --------------------------------


def test_denial_of_existence_phrasing_is_classified_as_denial():
    original_text = "この会社に代表者はいません。"
    item = _claim_item(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="explicit_denial",
        claimText="代表者はいない",
        sourceText="代表者はいません",
        sourceStartIndex=5,
        sourceEndIndex=13,
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert claim is not None
    assert claim.answerState == "explicit_denial"


# --- 「サービスを提供している可能性がある」(AI inference/evaluation) -------


def test_inference_phrasing_is_classified_as_ai_evaluation_or_inference():
    original_text = "この会社はSEO支援サービスを提供している可能性があります。"
    item = _claim_item(
        claimCategory="service",
        claimNature="ai_evaluation_or_inference",
        answerState="asserted",
        claimText="SEO支援サービスを提供している可能性がある",
        sourceText="SEO支援サービスを提供している可能性があります",
        sourceStartIndex=original_text.index("SEO支援"),
        sourceEndIndex=original_text.index("SEO支援") + len("SEO支援サービスを提供している可能性があります"),
        uncertaintyMarkers=["可能性がある"],
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert candidate.claimNature == "ai_evaluation_or_inference"
    assert claim is not None
    assert claim.claimNature == "ai_evaluation_or_inference"
    assert claim.uncertaintyMarkers == ["可能性がある"]


# --- 企業自身の宣伝的な自己申告 (self-reported claim) ------------------------


def test_self_promotional_phrasing_is_classified_as_self_reported_claim():
    original_text = "弊社は業界No.1のSEO支援会社です。"
    item = _claim_item(
        claimCategory="characteristic",
        claimNature="self_reported_claim",
        answerState="asserted",
        claimText="業界No.1のSEO支援会社と自称",
        sourceText="業界No.1のSEO支援会社です",
        sourceStartIndex=original_text.index("業界No.1"),
        sourceEndIndex=original_text.index("業界No.1") + len("業界No.1のSEO支援会社です"),
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert candidate.claimNature == "self_reported_claim"
    assert claim is not None
    assert claim.claimNature == "self_reported_claim"
    # Must not be conflated with an objective, independently-verifiable fact.
    assert claim.claimNature != "objective_fact"


# --- 数値・日付・単位の違い (numerical/date precision must survive as-is) --


def test_numerical_achievement_claim_preserves_the_quoted_number_exactly():
    original_text = "導入企業数は2026年時点で1,200社を超えています。"
    quoted = "2026年時点で1,200社を超えています"
    item = _claim_item(
        claimCategory="numerical_achievement",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="導入企業数は1,200社超",
        sourceText=quoted,
        sourceStartIndex=original_text.index(quoted),
        sourceEndIndex=original_text.index(quoted) + len(quoted),
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert claim is not None
    assert claim.sourceText == quoted
    assert "1,200" in claim.sourceText


def test_establishment_date_claim_with_different_unit_granularity():
    original_text = "設立は2010年4月です。"
    quoted = "2010年4月"
    item = _claim_item(
        claimCategory="establishment_date",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="設立は2010年4月",
        sourceText=quoted,
        sourceStartIndex=original_text.index(quoted),
        sourceEndIndex=original_text.index(quoted) + len(quoted),
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert claim is not None
    assert claim.sourceText == "2010年4月"


# --- 同じ文章の重複出現 (same sentence appears twice in the original) -----


def test_duplicate_sentence_is_verified_against_the_specific_claimed_occurrence():
    original_text = "ChatGPTによるとAcmeはSEO支援会社です。GeminiによるとAcmeはSEO支援会社です。"
    needle = "AcmeはSEO支援会社です"
    second_occurrence_start = original_text.rindex(needle)
    item = _claim_item(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="主要事業はSEO支援",
        sourceText=needle,
        sourceStartIndex=second_occurrence_start,
        sourceEndIndex=second_occurrence_start + len(needle),
    )
    candidate, claim = _parse_and_verify(original_text, item)
    assert claim is not None
    assert claim.sourceStartIndex == second_occurrence_start
