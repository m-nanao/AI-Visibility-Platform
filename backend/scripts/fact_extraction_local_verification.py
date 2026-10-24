#!/usr/bin/env python3
"""Task 6-D-5C-3B (feature/fact-extraction-local-verification-script):
a developer-only, local verification script for the Claude-based fact
extraction client — never imported by the application, never run by
any test, CI job, or production code path.

**Purpose**: answer the one genuinely unverified question from Task
6-D-5C-2/2A/2B's mock-only testing — what does the real Claude API
actually return (JSON compliance, `stop_reason`, token usage) for a
real ChatGPT no-search answer — without touching the production
database, the production quota/reservation mechanism, or any
production environment variable.

**What this script reuses, unmodified**: `services.fact_extraction_client`'s
`fetch_fact_extraction()` (the one function that makes the HTTP
request — this script calls it directly, as a single call, exactly as
every production caller does) and `services.fact_extraction`'s
`resolve_original_text()`-adjacent `verify_and_build_claims_with_diagnostics()`
(Task 6-D-5C-3C; the same span-verification/not_mentioned-split logic
`verify_and_build_claims()` uses in production, plus a diagnostic-only,
sourceText/claimText-free per-candidate breakdown this script prints —
see services/fact_extraction.py's own `ClaimVerificationDiagnostic`
docstring). `services.claude_settings.get_claude_credentials()`
and `services.fact_extraction_settings`'s model/token-limit settings
are reused as-is.

**What this script deliberately does NOT do**:
- It never calls `services.fact_extraction_provider.attempt_fact_extraction()`
  and never monkeypatches `reserve_websearch_quota_for_analysis_run()`
  — Task 6-D-5C-3B's own instruction. This script is not, and must
  never be described as, a test of the production quota/reservation
  path, which is already covered by
  tests/test_fact_extraction_provider.py and the disposable-PostgreSQL
  integration tests from Task 6-D-5C-2A/2B. It only exercises the
  Claude-calling/parsing/verification logic in isolation.
- It never connects to any database (production or otherwise).
- It never re-runs ChatGPT/Claude/Gemini/DataForSEO observations — the
  input text is supplied by the operator (a file or stdin), not
  fetched from any provider or any saved analysis run.
- It never retries, continues, or loops over multiple inputs. Exactly
  one `httpx.post()` call happens per script invocation, and only when
  `--execute` is passed; a defensive counter (`_HttpCallCounter`
  below) asserts this at runtime rather than merely documenting it.

**`fetch_fact_extraction()`'s own `FactExtractionClientResult` did not
originally expose Anthropic's `stop_reason`/`usage` fields** (Task
6-D-5C-2's production code never needed them — only this diagnostic
script does). Rather than duplicate fetch_fact_extraction()'s own
HTTP-call-and-parse sequence in this script (which would mean either a
second HTTP request, violating the "max 1 request" requirement, or a
second, drifting implementation of the same parsing logic), this task
added three new, backward-compatible, default-`None` fields directly
to `FactExtractionClientResult` (`stop_reason`/`input_tokens`/
`output_tokens` — see services/fact_extraction_client.py's own
docstring) — the one minimal interface change this task's own
instruction anticipated ("既存クライアントが単独で呼び出せない構造の
場合は...検証用の最小限の呼び出しインターフェースを検討し、既存処理
の大幅な変更は行わない"). No other change to that module was needed;
`fetch_fact_extraction()` itself was already directly callable with
simple, explicit parameters (credentials, brand_name, original_text,
model, max_output_tokens) — there was no structural obstacle to
calling it standalone.

**Dry-run by default.** Without `--execute`, this script performs
every step up to and including building the exact request body that
would be sent, prints it in full for the operator's own review (model,
max_output_tokens, system prompt length, and the full user prompt —
including the original text verbatim, so the operator can personally
confirm it contains no secret/confidential content before ever
deciding to pass `--execute`), and exits — zero HTTP requests, by
construction (the call to `fetch_fact_extraction()` is written inside
the `if args.execute:` branch only; there is no code path that reaches
it otherwise).

**Never logs**: the API key (never read into a local variable except
inside `ClaudeCredentials`, never printed), the raw Anthropic response
body (only the already-validated, derived fields this script's own
report prints), or any Authorization/x-api-key header.

**Note on the "max 1 request" guarantee's scope** (Task 6-D-5C-3B's
own required disclosure): this limit holds only within this one local
process's one invocation. It is not, and does not claim to be, the
production quota/reservation mechanism's cross-process guarantee
(`services.websearch_quota_reservation.reserve_websearch_quota_for_analysis_run()`,
already verified separately against a disposable PostgreSQL instance
in Task 6-D-5C-2A/2B) — running this script twice in a row, or from
two terminals at once, makes two independent real API calls, same as
calling `curl` twice would.

Usage:
    # Dry run (no API call) — reads original_text from a file.
    python3 scripts/fact_extraction_local_verification.py \\
        --brand-name "Acme" --input /path/to/chatgpt_answer.txt

    # Dry run reading from stdin.
    cat /path/to/chatgpt_answer.txt | \\
        python3 scripts/fact_extraction_local_verification.py --brand-name "Acme"

    # Real API call (exactly one request) — requires explicit opt-in
    # and CLAUDE_API_KEY to already be set in this shell's environment.
    python3 scripts/fact_extraction_local_verification.py \\
        --brand-name "Acme" --input /path/to/chatgpt_answer.txt --execute
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allows running this script directly (`python3 scripts/...py`) from
# the `backend/` directory without installing the package — mirrors
# how every test file in this backend resolves its imports (pytest.ini's
# `pythonpath = .`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import MAX_FACT_ORIGINAL_TEXT_CHARS  # noqa: E402
from services.claude_settings import get_claude_credentials  # noqa: E402
from services.fact_extraction import verify_and_build_claims_with_diagnostics  # noqa: E402
from services.fact_extraction_client import (  # noqa: E402
    build_fact_extraction_request_body,
    fetch_fact_extraction,
)
from services.fact_extraction_settings import (  # noqa: E402
    FACT_EXTRACTION_ALLOWED_MODELS,
    get_fact_extraction_max_output_tokens,
    get_fact_extraction_model,
)


class _HttpCallCounter:
    """Defensive, runtime-enforced version of this script's own "at
    most one HTTP request" requirement — not just a comment. Any
    second call to `increment_and_check()` within one process raises
    immediately, before a second `fetch_fact_extraction()` call could
    ever happen."""

    def __init__(self) -> None:
        self._count = 0

    def increment_and_check(self) -> None:
        self._count += 1
        if self._count > 1:
            raise RuntimeError(
                "Internal safety violation: this script attempted a second Claude API "
                "call within one invocation. Aborting before sending it."
            )

    @property
    def count(self) -> int:
        return self._count


def _read_input_text(input_path: str | None) -> str:
    if input_path:
        return Path(input_path).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        print(
            "No --input given and stdin is a terminal (nothing piped in). "
            "Pass --input <path> or pipe text via stdin.",
            file=sys.stderr,
        )
        sys.exit(2)
    return sys.stdin.read()


def _print_section(title: str) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local, dry-run-by-default verification of the Claude fact-extraction "
            "client against a real ChatGPT no-search answer. See this file's own "
            "module docstring for the full safety contract."
        )
    )
    parser.add_argument(
        "--brand-name", required=True, help="The subject brand name (sent to Claude)."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to a UTF-8 text file containing the ChatGPT no-search answer. "
        "Reads from stdin if omitted.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model id (still checked against the allowlist). "
        "Defaults to FACT_EXTRACTION_MODEL / the built-in default.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call the Claude API (exactly one request). Without this flag, "
        "the script only previews what would be sent and makes zero HTTP requests.",
    )
    args = parser.parse_args()

    original_text = _read_input_text(args.input)

    if not original_text.strip():
        print("ERROR: the input text is blank.", file=sys.stderr)
        return 1

    # Task 6-D-5C-3B item 2: "20,000文字上限を維持" / "原文を変更しない"
    # — refuses outright rather than silently truncating, mirroring
    # services/fact_extraction_provider.py's own "input_too_long" skip
    # behavior in production.
    if len(original_text) > MAX_FACT_ORIGINAL_TEXT_CHARS:
        print(
            f"ERROR: input text is {len(original_text)} characters, exceeding the "
            f"{MAX_FACT_ORIGINAL_TEXT_CHARS}-character limit. Refusing to truncate or "
            "proceed — this mirrors production's own input_too_long skip behavior.",
            file=sys.stderr,
        )
        return 1

    model = args.model or get_fact_extraction_model()
    if model not in FACT_EXTRACTION_ALLOWED_MODELS:
        print(
            f"ERROR: model {model!r} is not on the allowlist {sorted(FACT_EXTRACTION_ALLOWED_MODELS)!r}. "
            "Refusing to call an unapproved model.",
            file=sys.stderr,
        )
        return 1
    max_output_tokens = get_fact_extraction_max_output_tokens()

    credentials = get_claude_credentials()
    if args.execute and credentials is None:
        print(
            "ERROR: --execute was given but CLAUDE_API_KEY is not set in this shell's "
            "environment. Set it locally (never in a committed file) before retrying.",
            file=sys.stderr,
        )
        return 1

    # --- Preview: exactly what would be sent, for the operator's own
    # review before deciding whether to pass --execute. This is the
    # one place the input text is printed, deliberately, so the
    # operator can personally confirm it contains nothing confidential
    # (Task 6-D-5C-3B item 2's own "原文に秘密情報が含まれていないこと
    # を確認する" — a human judgment call this script surfaces the
    # exact input for, rather than attempting an unreliable automated
    # secret-detection heuristic).
    body = build_fact_extraction_request_body(
        args.brand_name, original_text, model=model, max_output_tokens=max_output_tokens
    )
    _print_section("REQUEST PREVIEW (nothing sent yet)")
    print(f"model: {model}")
    print(f"max_output_tokens: {max_output_tokens}")
    print(f"system prompt length: {len(body['system'])} chars")
    print(f"original_text length: {len(original_text)} chars")
    print("--- full user prompt that would be sent (review before --execute) ---")
    print(body["messages"][0]["content"])
    print("--- end of user prompt ---")

    if not args.execute:
        _print_section("DRY RUN")
        print("0 HTTP requests made. Pass --execute to make exactly one real Claude API call.")
        return 0

    call_counter = _HttpCallCounter()

    _print_section("EXECUTING (1 real Claude API request)")
    call_counter.increment_and_check()
    client_result = fetch_fact_extraction(
        credentials, args.brand_name, original_text, model=model, max_output_tokens=max_output_tokens
    )

    verification, diagnostics = verify_and_build_claims_with_diagnostics(
        client_result.candidates,
        original_text=original_text,
        source_platform="chatgpt",
        observation_method=None,
        source_model=None,
        extraction_model=model,
        brand_name=args.brand_name,
    )

    _print_section("RESULT")
    print(f"http_request_count: {call_counter.count}")
    print(f"model: {model}")
    print(f"stop_reason: {client_result.stop_reason}")
    print(f"input_tokens: {client_result.input_tokens}")
    print(f"output_tokens: {client_result.output_tokens}")
    print(f"json_parse_success: {client_result.success}")
    if not client_result.success:
        print(f"failure_reason: {client_result.reason}")
    print(f"candidates_from_claude: {len(client_result.candidates)}")
    print(f"malformed_candidate_count: {client_result.malformed_candidate_count}")
    print(f"claims_accepted (span-verified): {len(verification.claims)}")
    print(f"not_mentioned_categories: {len(verification.notMentionedCategories)}")
    print(f"rejectedCount (verification + malformed): "
          f"{verification.rejectedCount + client_result.malformed_candidate_count}")
    print(f"claims_truncated_by_cap: {verification.truncated}")

    total_considered = len(client_result.candidates)
    if total_considered:
        span_match_rate = len(verification.claims) / total_considered
        print(f"span_match_rate (claims accepted / candidates considered): {span_match_rate:.0%}")
    else:
        print("span_match_rate: N/A (no candidates to evaluate)")

    overlap = {c.claimCategory for c in verification.claims} & {
        c.claimCategory for c in verification.notMentionedCategories
    }
    print(f"claims/notMentionedCategories category overlap (must be empty): {sorted(overlap)}")

    # Task 6-D-5C-3C: per-candidate diagnostic breakdown — explains
    # every one of rejectedCount's rejections by reason code, without
    # ever printing a candidate's own sourceText/claimText (which may
    # quote the AI answer at length). Safe to paste into a report as-
    # is; this is the whole reason this breakdown exists — Task
    # 6-D-5C-3B-4's real run had no way to explain its own 4 rejections
    # without a second API call, which is never allowed.
    _print_section("PER-CANDIDATE DIAGNOSTICS (no sourceText/claimText — safe to report in full)")
    for diagnostic in diagnostics:
        outcome = "accepted" if diagnostic.accepted else f"rejected({diagnostic.rejectionReason})"
        print(
            f"- candidate[{diagnostic.candidateIndex}] "
            f"category={diagnostic.claimCategory} answerState={diagnostic.answerState} "
            f"-> {outcome} "
            f"sourceTextOccurrenceCount={diagnostic.sourceTextOccurrenceCount} "
            f"spanWasCorrected={diagnostic.spanWasCorrected} "
            f"claimTextLength={diagnostic.claimTextLength} sourceTextLength={diagnostic.sourceTextLength}"
        )
    diagnostics_accepted = sum(1 for d in diagnostics if d.accepted)
    diagnostics_rejected = sum(1 for d in diagnostics if not d.accepted)
    print(
        f"diagnostics_accepted={diagnostics_accepted} diagnostics_rejected={diagnostics_rejected} "
        f"(accepted must equal claims_accepted + not_mentioned_categories; "
        f"rejected must equal rejectedCount shown above, malformed candidates excluded — "
        "those never reach verification at all)"
    )
    corrected_count = sum(1 for d in diagnostics if d.spanWasCorrected)
    print(f"claims_accepted_via_span_correction: {corrected_count}")

    if verification.claims:
        _print_section("ACCEPTED CLAIMS (review for semantic correctness — a verified span is NOT a truth guarantee)")
        for claim in verification.claims:
            print(
                f"- [{claim.claimCategory}/{claim.claimNature}/{claim.answerState}] "
                f"claimText={claim.claimText!r} sourceText={claim.sourceText!r} "
                f"span=({claim.sourceStartIndex},{claim.sourceEndIndex}) "
                f"uncertaintyMarkers={claim.uncertaintyMarkers}"
            )

    if verification.notMentionedCategories:
        _print_section("NOT-MENTIONED CATEGORIES")
        for category_state in verification.notMentionedCategories:
            print(f"- {category_state.claimCategory}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
