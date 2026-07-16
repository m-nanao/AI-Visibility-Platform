"""AI Overview comparison provider — a swappable data source for the
`aiOverviewComparison` section, so a future real DataForSEO connection
only touches this module (and its single call site in main.py) rather
than being threaded through the rest of the analysis pipeline.

This exists specifically to prevent an accidental real (potentially
billed) DataForSEO call during development or testing. Two independent
gates have to agree before anything other than fixed mock data can be
returned:

1. `AI_OVERVIEW_PROVIDER_MODE` (env var, default "mock") — the
   operator-controlled default for the whole service.
2. `ALLOW_AI_OVERVIEW_MODE_OVERRIDE` (env var, default false) — whether
   a per-request `aiOverviewMode` field is honored at all. When this is
   false (the default), a caller can put any value it likes in the
   request body and it changes nothing; only the environment default
   applies.

Three modes:

- "mock": fixed development data (unchanged from what previously lived
  directly in services/mock_analysis.py). Section status: "mock".
- "off": the section is disabled outright. Returns []. Section status:
  "unavailable" (there is no separate "disabled" status in
  SectionStatus yet — see docs/07_decisions.md's rationale for why
  "unavailable" already means "couldn't be computed", which fits).
- "dataforseo": **NOT YET IMPLEMENTED.** No external API call is made
  under any circumstances in this module — this deliberately returns
  [] / "unavailable" rather than ever faking a "real" result, so a
  misconfigured environment can never be mistaken for a working
  DataForSEO integration. See docs/05_tasks.md for the follow-up task
  that will replace this branch with an actual DataForSEO call.
"""

import logging
import os

from models import AIOverviewComparisonItem, AiOverviewProviderMode, SectionStatus

logger = logging.getLogger(__name__)

_VALID_MODES: tuple[AiOverviewProviderMode, ...] = ("mock", "off", "dataforseo")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_mode_from_env() -> AiOverviewProviderMode:
    raw = os.environ.get("AI_OVERVIEW_PROVIDER_MODE", "mock").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "AI_OVERVIEW_PROVIDER_MODE=%r is not one of %s; falling back to \"mock\"",
            raw,
            _VALID_MODES,
        )
        return "mock"
    return raw  # type: ignore[return-value]


def resolve_ai_overview_mode(
    request_override: AiOverviewProviderMode | None,
) -> AiOverviewProviderMode:
    """Decides which mode to run for this request.

    `request_override` (AnalyzeRequest.aiOverviewMode) is only honored
    when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true — otherwise the
    environment default (AI_OVERVIEW_PROVIDER_MODE) is used regardless
    of what the caller sent, so a request body alone can never turn on
    a paid provider in an environment that isn't configured to allow it.
    """
    default_mode = _default_mode_from_env()
    if request_override is None:
        return default_mode
    if not _env_flag("ALLOW_AI_OVERVIEW_MODE_OVERRIDE"):
        return default_mode
    return request_override


def build_mock_ai_overview_comparison(brand_name: str) -> list[AIOverviewComparisonItem]:
    """Fixed development fixture, not derived from `brand_name` (kept
    as a parameter for signature symmetry with the real provider this
    will eventually be swapped for, and in case the mock is made
    brand-aware later)."""
    del brand_name
    return [
        AIOverviewComparisonItem(
            platform="Google AI Overview",
            mentioned=True,
            rank=2,
            summary="比較記事からの引用として2番目に表示されることが多い。",
        ),
        AIOverviewComparisonItem(
            platform="ChatGPT",
            mentioned=True,
            rank=1,
            summary="関連する質問に対して第一想起として挙げられる頻度が高い。",
        ),
        AIOverviewComparisonItem(
            platform="Perplexity",
            mentioned=True,
            rank=3,
            summary="情報源として公式サイトとレビューサイトが引用される傾向。",
        ),
        AIOverviewComparisonItem(
            platform="Copilot",
            mentioned=False,
            rank=None,
            summary="現時点では明確な言及が確認されていません。",
        ),
    ]


def build_ai_overview_comparison(
    brand_name: str, mode: AiOverviewProviderMode
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str]:
    """Returns (items, section status, human-readable reason) for the
    given mode. Never calls an external API regardless of mode — see
    module docstring for why "dataforseo" is a deliberate stub, not a
    real connection, as of this task.
    """
    if mode == "off":
        return (
            [],
            "unavailable",
            "AI Overview comparison is disabled (AI_OVERVIEW_PROVIDER_MODE=off).",
        )

    if mode == "dataforseo":
        return (
            [],
            "unavailable",
            "DataForSEO provider is not yet implemented; no external API call was made.",
        )

    # mode == "mock" — also the effective fallback for any unrecognized
    # value, since resolve_ai_overview_mode()/_default_mode_from_env()
    # already normalize to one of _VALID_MODES before this is called.
    return (
        build_mock_ai_overview_comparison(brand_name),
        "mock",
        "Using mock AI Overview data for development.",
    )
