"""AI Overview comparison provider — a swappable data source for the
`aiOverviewComparison` section, so a real DataForSEO connection only
touches this module (and its single call site in main.py) rather than
being threaded through the rest of the analysis pipeline.

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
- "dataforseo": Connects to DataForSEO — **Sandbox by default, Live
  only for a deliberate, fully-gated one-off manual check** (see
  `_run_dataforseo_mode()` below and docs/07_decisions.md for the full
  rationale). When `DATAFORSEO_API_ENV=sandbox` and credentials are
  configured, this calls services/dataforseo_client.py's connector
  against the Sandbox host — by default against DataForSEO's Google AI
  Mode endpoint (`DATAFORSEO_SERP_ENDPOINT=google_ai_mode_live_advanced`,
  the only endpoint manually confirmed to reliably surface an
  `ai_overview` item; see docs/07_decisions.md) — and reports "real"
  only if a usable AI Overview-type item was actually found and
  parsed. When `DATAFORSEO_API_ENV=live`, the same connector is used
  against the Live host, but **only** once
  `DataForSEOSettings.is_live_allowed_for_manual_check` confirms five
  independent env-var gates are all satisfied at once
  (`DATAFORSEO_LIVE_API_ENABLED=true`,
  `DATAFORSEO_LIVE_CONFIRM_TEXT=ALLOW_DATAFORSEO_LIVE_ONCE`,
  `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=1`, credentials configured, and
  `DATAFORSEO_API_ENV=live` itself) — any single gate missing means no
  external call is made at all. Either way, any failure (missing
  credentials, network error, unexpected response shape, no matching
  item, insufficient Live gates) falls back to []/"unavailable" with a
  safe, credential-free `reason` explaining why. `/analyze` itself
  never fails because of this — a DataForSEO problem only ever affects
  this one section.
"""

import logging
import os

from models import AIOverviewComparisonItem, AiOverviewEnvironment, AiOverviewProviderMode, SectionStatus
from services.dataforseo_client import fetch_ai_overview_serp
from services.dataforseo_settings import (
    DataForSEOApiEnv,
    DataForSEOSettings,
    get_dataforseo_credentials,
    get_dataforseo_settings,
)

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


_ENVIRONMENT_PLATFORM_LABELS: dict[DataForSEOApiEnv, str] = {
    "sandbox": "Google AI Mode (DataForSEO Sandbox)",
    "live": "Google AI Mode (DataForSEO Live)",
}


def _live_gate_rejection_reason(settings: DataForSEOSettings) -> str:
    """Produces the most specific reason why the Live manual-check gate
    (settings.is_live_allowed_for_manual_check) was not satisfied.
    Credentials are already confirmed present by the time this is
    called (see _run_dataforseo_mode), so that's never the cause here.

    Checked in order from "most fundamental switch" to "most specific
    detail", so an unconfigured environment (the common case) gets the
    general "disabled" message, while an operator who got partway
    through the manual-check checklist gets a message pointing at
    exactly what's still missing.
    """
    if not settings.live_api_enabled:
        return (
            "DataForSEO Live API is disabled. Set all manual live confirmation "
            "gates to enable one manual request."
        )
    if not settings.live_confirm_text_matches:
        return "DataForSEO Live API requires explicit manual confirmation."
    # live_api_enabled and live_confirm_text_matches both hold — per
    # is_live_allowed_for_manual_check's own definition, the only gate
    # that can still be unmet here is the request limit.
    return "DataForSEO Live API request limit must be 1."


def _call_dataforseo_serp(
    brand_name: str, settings: DataForSEOSettings, *, api_env: DataForSEOApiEnv
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Shared by both the Sandbox and (gate-confirmed) Live paths —
    the only difference between them is which host `api_env` selects
    (see services/dataforseo_client.py); the response handling,
    conversion to AIOverviewComparisonItem, and safe-failure behavior
    are identical either way.
    """
    credentials = get_dataforseo_credentials()
    if credentials is None:
        # Defensive: is_configured already implies this can't happen.
        return (
            [],
            "unavailable",
            "DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).",
            "unavailable",
        )

    result = fetch_ai_overview_serp(
        credentials,
        brand_name,
        api_env=api_env,
        endpoint=settings.serp_endpoint,
        location_code=settings.location_code,
        language_code=settings.language_code,
        device=settings.device,
        os_name=settings.os,
    )
    if not result.success:
        return [], "unavailable", result.reason, "unavailable"

    items = [
        AIOverviewComparisonItem(
            platform=_ENVIRONMENT_PLATFORM_LABELS[api_env],
            mentioned=result.mentioned,
            rank=result.rank,
            summary=result.summary or "",
        )
    ]
    return items, "real", result.reason, api_env


def _run_dataforseo_mode(
    brand_name: str, settings: DataForSEOSettings
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Implements the "dataforseo" mode's full decision tree. Never
    includes settings.login or the password itself (which isn't even
    held anywhere, see services/dataforseo_settings.py) in any reason
    string.

    Sandbox is called whenever DATAFORSEO_API_ENV=sandbox and
    credentials are configured — this is the safe, no-cost default
    path. Live is called only when
    settings.is_live_allowed_for_manual_check is True, i.e. every one
    of the five manual-confirmation gates holds at once; a single
    missing gate falls back to []/"unavailable" without ever
    constructing a request against the Live host (see
    services/dataforseo_client.py's module docstring for why the
    client itself has no gating logic of its own — this function is
    the one and only place that decision is made).
    """
    if not settings.is_configured:
        return (
            [],
            "unavailable",
            "DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).",
            "unavailable",
        )

    if settings.is_live_env:
        if not settings.is_live_allowed_for_manual_check:
            return ([], "unavailable", _live_gate_rejection_reason(settings), "unavailable")
        return _call_dataforseo_serp(brand_name, settings, api_env="live")

    # settings.is_sandbox_env and credentials are configured — the
    # default, always-safe path.
    return _call_dataforseo_serp(brand_name, settings, api_env="sandbox")


def build_ai_overview_comparison(
    brand_name: str, mode: AiOverviewProviderMode
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Returns (items, section status, human-readable reason,
    environment) for the given mode. "mock"/"off" never call an
    external API. "dataforseo" calls DataForSEO Sandbox by default, or
    Live only when every manual-check gate is satisfied — see module
    docstring and _run_dataforseo_mode() for the full decision tree.

    `environment` exists because `status` alone can't distinguish a
    Sandbox success from a Live success (both report "real") — see
    models.AiOverviewEnvironment and app/lib/meta-label.ts's
    getAiOverviewProviderStatusDisplay() for how the UI uses it.
    """
    if mode == "off":
        return (
            [],
            "unavailable",
            "AI Overview comparison is disabled (AI_OVERVIEW_PROVIDER_MODE=off).",
            "off",
        )

    if mode == "dataforseo":
        return _run_dataforseo_mode(brand_name, get_dataforseo_settings())

    # mode == "mock" — also the effective fallback for any unrecognized
    # value, since resolve_ai_overview_mode()/_default_mode_from_env()
    # already normalize to one of _VALID_MODES before this is called.
    return (
        build_mock_ai_overview_comparison(brand_name),
        "mock",
        "Using mock AI Overview data for development.",
        "mock",
    )
