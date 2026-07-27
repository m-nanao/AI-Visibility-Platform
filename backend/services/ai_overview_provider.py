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

Five modes:

- "mock": fixed development data (unchanged from what previously lived
  directly in services/mock_analysis.py). Section status: "mock".
- "off": the section is disabled outright. Returns []. Section status:
  "unavailable" (there is no separate "disabled" status in
  SectionStatus yet — see docs/07_decisions.md's rationale for why
  "unavailable" already means "couldn't be computed", which fits).
- "dataforseo": **env-driven, kept for backwards compatibility.**
  Connects to DataForSEO — **Sandbox by default, Live only for a
  deliberate, fully-gated one-off manual check** (see
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
  external call is made at all.
- "dataforseo_sandbox": **explicit, recommended for normal
  verification/demo use.** Forces the Sandbox host regardless of what
  `DATAFORSEO_API_ENV` happens to be set to — no Live gate is involved
  at all, since Sandbox is never billed. Only requires credentials to
  be configured; see `_run_dataforseo_sandbox_mode()`.
- "dataforseo_live": **explicit, for a deliberate one-off Live check.**
  Still only actually calls the Live host once every one of the same
  five manual-confirmation gates `is_live_allowed_for_manual_check`
  checks holds — including `DATAFORSEO_API_ENV=live` itself, since
  selecting this mode does not by itself flip the environment. See
  `_run_dataforseo_live_mode()`. Unlike "dataforseo" (which silently
  falls back to Sandbox when `DATAFORSEO_API_ENV` isn't "live"),
  requesting "dataforseo_live" while a gate is unmet is reported with a
  reason that explicitly says Live mode was requested but a specific
  gate is missing — see `_explicit_live_gate_rejection_reason()`.

Either way, any failure (missing credentials, network error,
unexpected response shape, no matching item, insufficient Live gates)
falls back to []/"unavailable" with a safe, credential-free `reason`
explaining why. `/analyze` itself never fails because of this — a
DataForSEO problem only ever affects this one section.

On a "dataforseo" success, AIOverviewComparisonItem also carries
`fullSummary` (a longer, still-bounded excerpt), `references` (up to 10
deduplicated citations), and `ownDomainReferenced` (whether any
reference's domain matches one of the request's own input `urls` — a
simple domain-string comparison, None when the request had no `urls` to
compare against). None of this changes the gating above — it only
enriches an already-successful DataForSEO response; see
_call_dataforseo_serp and _determine_own_domain_referenced.

Each reference also gets a simple, rule-based `category` (see
models.ReferenceCategory and _classify_reference_category below) —
"official" for an own-domain match, otherwise matched against small
hardcoded domain lists (Wikipedia/SNS/UGC/video/news) or "other".
`referenceSummary` (see _build_reference_summary) rolls those
categories up into a total/official/thirdParty/categories count. Both
are derived entirely from data this module already has (references +
the request's own input `urls`) — no new DataForSEO request, no
external classification service.
"""

import logging
import os
from urllib.parse import urlparse

from models import (
    AIOverviewComparisonItem,
    AIOverviewReference,
    AIOverviewReferenceCategoryCounts,
    AIOverviewReferenceSummary,
    AiOverviewEnvironment,
    AiOverviewProviderMode,
    ReferenceCategory,
    SectionStatus,
)
from services.dataforseo_client import DataForSEOSerpReference, fetch_ai_overview_serp
from services.dataforseo_settings import (
    DataForSEOApiEnv,
    DataForSEOSettings,
    get_dataforseo_credentials,
    get_dataforseo_settings,
)

logger = logging.getLogger(__name__)

_VALID_MODES: tuple[AiOverviewProviderMode, ...] = (
    "mock",
    "off",
    "dataforseo",
    "dataforseo_sandbox",
    "dataforseo_live",
)


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


def _explicit_live_gate_rejection_reason(settings: DataForSEOSettings, credentials_configured: bool) -> str:
    """Reason for why "dataforseo_live" mode couldn't call the Live
    host. Unlike _live_gate_rejection_reason above (only ever called
    after settings.is_live_env is already confirmed true, since
    "dataforseo" mode only reaches the Live branch when
    DATAFORSEO_API_ENV=live), "dataforseo_live" can be explicitly
    requested while DATAFORSEO_API_ENV is still "sandbox" (or unset) —
    so is_live_env itself has to be checked here too, and the message
    says so explicitly rather than assuming the operator already knows
    Live mode requires DATAFORSEO_API_ENV=live.

    Checked in order from "most fundamental" to "most specific" (same
    ordering rationale as _live_gate_rejection_reason), so an operator
    who got partway through the manual-check checklist gets a message
    pointing at exactly what's still missing. Never includes
    settings.login or the password itself (see module docstring).
    """
    if not credentials_configured:
        return (
            "DataForSEO Live mode was requested, but DataForSEO credentials are not "
            "configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD)."
        )
    if not settings.is_live_env:
        return "DataForSEO Live mode was requested, but DATAFORSEO_API_ENV is not live."
    if not settings.live_api_enabled:
        return "DataForSEO Live mode was requested, but DATAFORSEO_LIVE_API_ENABLED is not true."
    if not settings.live_confirm_text_matches:
        return (
            "DataForSEO Live mode was requested, but DATAFORSEO_LIVE_CONFIRM_TEXT does not "
            "match the required confirmation text."
        )
    # credentials, is_live_env, live_api_enabled, and live_confirm_text_matches
    # all hold — per is_live_allowed_for_manual_check's own definition, the
    # only gate that can still be unmet here is the request limit.
    return "DataForSEO Live mode was requested, but request limit is not 1."


def _extract_domain(url: str) -> str | None:
    """Best-effort hostname extraction, lowercased and with a leading
    "www." stripped so "https://www.example.com/x" and
    "https://example.com" compare equal. Returns None for anything that
    doesn't parse to a usable netloc (e.g. a bare keyword, not a URL).
    """
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return None
    # Strip userinfo ("user:pass@") and port, in case either is present.
    netloc = netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def _own_domains(input_urls: list[str] | None) -> set[str]:
    """The set of domains behind the request's own input `urls` — the
    candidate "own domain(s)" ownDomainReferenced checks references
    against. Empty when there were no input urls (e.g. the request used
    `documents` or the development sample instead), which is exactly
    when ownDomainReferenced can't be determined at all (see
    _determine_own_domain_referenced).
    """
    if not input_urls:
        return set()
    domains = {domain for url in input_urls if (domain := _extract_domain(url))}
    return domains


def _reference_domain(reference: DataForSEOSerpReference) -> str | None:
    if reference.domain:
        domain = reference.domain.lower()
        return domain[4:] if domain.startswith("www.") else domain
    if reference.url:
        return _extract_domain(reference.url)
    return None


def _determine_own_domain_referenced(
    own_domains: set[str], references: tuple[DataForSEOSerpReference, ...]
) -> bool | None:
    """Whether any of `references` shares a domain with `own_domains` —
    a simple domain-string match, not a content/ownership check. None
    when there's nothing to compare against (no input urls), which the
    frontend renders as "unjudged" rather than a false negative.
    """
    if not own_domains:
        return None
    return any(_reference_domain(reference) in own_domains for reference in references)


# Simple, hardcoded domain lists for _classify_reference_category()'s
# rule-based (not AI-driven) classification — deliberately small and
# non-exhaustive (see docs/07_decisions.md and ReferenceCategory's own
# docstring in models.py). "media" has no domain list of its own yet:
# anything not matched below (and not an official/own-domain match)
# falls back to "other" rather than being guessed at.
_WIKIPEDIA_DOMAINS = ("wikipedia.org",)
_SNS_DOMAINS = ("x.com", "twitter.com", "facebook.com", "instagram.com", "linkedin.com", "threads.net")
_UGC_DOMAINS = (
    "qiita.com",
    "zenn.dev",
    "note.com",
    "hatena.ne.jp",
    "chiebukuro.yahoo.co.jp",
    "reddit.com",
    "stackoverflow.com",
)
_VIDEO_DOMAINS = ("youtube.com", "youtu.be")
_NEWS_DOMAINS = (
    "nikkei.com",
    "asahi.com",
    "yomiuri.co.jp",
    "mainichi.jp",
    "sankei.com",
    "nhk.or.jp",
    "reuters.com",
    "bloomberg.co.jp",
)

# Checked in this order — "official" (an own-domain match) is decided
# separately, before this list is even consulted (see
# _classify_reference_category), so it can never be shadowed by one of
# these.
_CATEGORY_DOMAIN_HINTS: tuple[tuple[ReferenceCategory, tuple[str, ...]], ...] = (
    ("wikipedia", _WIKIPEDIA_DOMAINS),
    ("sns", _SNS_DOMAINS),
    ("ugc", _UGC_DOMAINS),
    ("video", _VIDEO_DOMAINS),
    ("news", _NEWS_DOMAINS),
)


def _domain_matches(domain: str, known_domain: str) -> bool:
    """True if `domain` is exactly `known_domain`, or a subdomain of it
    (e.g. "ja.wikipedia.org" matches "wikipedia.org", "docs.cybozu.co.jp"
    matches "cybozu.co.jp"). Both sides are expected to already be
    lowercased with any "www." stripped (see _reference_domain).
    """
    return domain == known_domain or domain.endswith("." + known_domain)


def _classify_reference_category(
    reference: DataForSEOSerpReference, own_domains: set[str]
) -> ReferenceCategory:
    """Rule-based (not AI-driven) classification from the reference's
    own domain alone — see models.ReferenceCategory for the full
    rationale. Checked in order: an own-domain (subdomain-inclusive)
    match is "official" first, before any of the hardcoded
    Wikipedia/SNS/UGC/video/news domain lists are even consulted, so a
    brand's own domain can never be miscategorized as one of those.
    Anything left over (including anything that would need a "media"
    judgment call) is "other".
    """
    domain = _reference_domain(reference)
    if domain is None:
        return "other"

    if any(_domain_matches(domain, own_domain) for own_domain in own_domains):
        return "official"

    for category, known_domains in _CATEGORY_DOMAIN_HINTS:
        if any(_domain_matches(domain, known_domain) for known_domain in known_domains):
            return category

    return "other"


def _to_model_references(
    references: tuple[DataForSEOSerpReference, ...], own_domains: set[str]
) -> list[AIOverviewReference]:
    return [
        AIOverviewReference(
            title=reference.title,
            domain=reference.domain,
            url=reference.url,
            text=reference.text,
            source=reference.source,
            position=reference.position,
            category=_classify_reference_category(reference, own_domains),
        )
        for reference in references
    ]


def _build_reference_summary(
    references: list[AIOverviewReference] | None,
) -> AIOverviewReferenceSummary | None:
    """Rolls up `references`' categories into a total/official/
    thirdParty/categories summary (see AIOverviewReferenceSummary).
    None when there are no references at all — there's nothing to
    summarize, so the frontend can treat "no summary" the same way it
    already treats "no references".
    """
    if not references:
        return None

    counts: dict[str, int] = {}
    official_count = 0
    for reference in references:
        category = reference.category or "other"
        counts[category] = counts.get(category, 0) + 1
        if category == "official":
            official_count += 1

    total = len(references)
    return AIOverviewReferenceSummary(
        total=total,
        official=official_count,
        thirdParty=total - official_count,
        categories=AIOverviewReferenceCategoryCounts(**counts),
    )


def _call_dataforseo_serp(
    brand_name: str,
    settings: DataForSEOSettings,
    *,
    api_env: DataForSEOApiEnv,
    input_urls: list[str] | None = None,
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

    own_domains = _own_domains(input_urls)
    own_domain_referenced = _determine_own_domain_referenced(own_domains, result.references)
    model_references = _to_model_references(result.references, own_domains) or None

    items = [
        AIOverviewComparisonItem(
            platform=_ENVIRONMENT_PLATFORM_LABELS[api_env],
            mentioned=result.mentioned,
            rank=result.rank,
            summary=result.summary or "",
            fullSummary=result.full_summary,
            references=model_references,
            referenceSummary=_build_reference_summary(model_references),
            ownDomainReferenced=own_domain_referenced,
        )
    ]
    return items, "real", result.reason, api_env


def _run_dataforseo_mode(
    brand_name: str, settings: DataForSEOSettings, input_urls: list[str] | None = None
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

    `input_urls` (the request's `urls`, if any) is only used to decide
    AIOverviewComparisonItem.ownDomainReferenced — it never affects
    which environment/gates are checked above.
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
        return _call_dataforseo_serp(brand_name, settings, api_env="live", input_urls=input_urls)

    # settings.is_sandbox_env and credentials are configured — the
    # default, always-safe path.
    return _call_dataforseo_serp(brand_name, settings, api_env="sandbox", input_urls=input_urls)


def _run_dataforseo_sandbox_mode(
    brand_name: str, settings: DataForSEOSettings, input_urls: list[str] | None = None
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Implements "dataforseo_sandbox" mode: forces the Sandbox host
    regardless of settings.api_env (DATAFORSEO_API_ENV) — no Live gate
    is consulted at all, since Sandbox is never billed. The only
    requirement is that credentials are configured.
    """
    if not settings.is_configured:
        return (
            [],
            "unavailable",
            "DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).",
            "unavailable",
        )
    return _call_dataforseo_serp(brand_name, settings, api_env="sandbox", input_urls=input_urls)


def _run_dataforseo_live_mode(
    brand_name: str, settings: DataForSEOSettings, input_urls: list[str] | None = None
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Implements "dataforseo_live" mode: calls the Live host only once
    settings.is_live_allowed_for_manual_check confirms every one of the
    five manual-confirmation gates holds (same property "dataforseo"
    mode's Live branch checks) — including DATAFORSEO_API_ENV=live
    itself, since requesting this mode does not by itself change the
    environment. A single missing gate means no request is ever built
    against the Live host; see _explicit_live_gate_rejection_reason for
    the (gate-specific, credential-free) reason text.
    """
    if not settings.is_live_allowed_for_manual_check:
        return (
            [],
            "unavailable",
            _explicit_live_gate_rejection_reason(settings, settings.is_configured),
            "unavailable",
        )
    return _call_dataforseo_serp(brand_name, settings, api_env="live", input_urls=input_urls)


def build_ai_overview_comparison(
    brand_name: str, mode: AiOverviewProviderMode, input_urls: list[str] | None = None
) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]:
    """Returns (items, section status, human-readable reason,
    environment) for the given mode. "mock"/"off" never call an
    external API. "dataforseo" calls DataForSEO Sandbox by default, or
    Live only when every manual-check gate is satisfied (env-driven,
    see _run_dataforseo_mode()). "dataforseo_sandbox"/"dataforseo_live"
    are the explicit variants — see module docstring and
    _run_dataforseo_sandbox_mode()/_run_dataforseo_live_mode() for the
    full decision tree of each.

    `environment` exists because `status` alone can't distinguish a
    Sandbox success from a Live success (both report "real") — see
    models.AiOverviewEnvironment and app/lib/meta-label.ts's
    getAiOverviewProviderStatusDisplay() for how the UI uses it.

    `input_urls` is the request's own `urls` field (None when the
    request used `documents`/the development sample instead) — passed
    through only to determine ownDomainReferenced on a dataforseo
    success; it has no effect on "mock"/"off" or on which DataForSEO
    gates are checked.
    """
    if mode == "off":
        return (
            [],
            "unavailable",
            "AI Overview comparison is disabled (AI_OVERVIEW_PROVIDER_MODE=off).",
            "off",
        )

    if mode == "dataforseo":
        return _run_dataforseo_mode(brand_name, get_dataforseo_settings(), input_urls)

    if mode == "dataforseo_sandbox":
        return _run_dataforseo_sandbox_mode(brand_name, get_dataforseo_settings(), input_urls)

    if mode == "dataforseo_live":
        return _run_dataforseo_live_mode(brand_name, get_dataforseo_settings(), input_urls)

    # mode == "mock" — also the effective fallback for any unrecognized
    # value, since resolve_ai_overview_mode()/_default_mode_from_env()
    # already normalize to one of _VALID_MODES before this is called.
    return (
        build_mock_ai_overview_comparison(brand_name),
        "mock",
        "Using mock AI Overview data for development.",
        "mock",
    )
