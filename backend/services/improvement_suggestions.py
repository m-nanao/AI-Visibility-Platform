"""Lightweight, rule-based improvement suggestions derived from
analysis already computed elsewhere in the pipeline.

This turns the existing cooccurrenceRanking/contextAnalysis/summary
outputs into ImprovementSuggestion[] — the last mock-by-default
section (besides aiOverviewComparison) to become real. Deliberately
simple, in the same spirit as services/context_analysis.py and
services/brand_summary.py:

- No AI/LLM calls, no external API (no DataForSEO) — this module never
  calls DataForSEO itself. It does read `ai_overview_items`
  (aiOverviewComparison, computed separately by
  services/ai_overview_provider.py) for at most one suggestion about
  AI Overview reference state (_ai_overview_reference_suggestion) —
  that's a no-op unless aiOverviewComparison already ran in
  "dataforseo" mode, so it never triggers an extra request on its own.
  Every other suggestion comes from a small, explainable condition over
  data already computed by services/cooccurrence.py,
  services/context_analysis.py, and services/brand_summary.py.
- Every suggestion states its own reason in `description` (e.g. "料金
  カテゴリの文脈が確認できないため...") so a reader can see why it was
  produced without needing to inspect this module's source.
- This is MVP-grade triage, not a substitute for a human SEO/LLMO
  judgment call — see the module-level caveat repeated in
  build_improvement_suggestions()'s docstring.
"""

from models import (
    AIOverviewComparisonItem,
    BrandSummary,
    CommonCrawlProviderInfo,
    ContextAnalysisItem,
    CooccurrenceKeyword,
    ImprovementSuggestion,
    Priority,
)
from services.context_analysis import CATEGORY_LABELS

# Reverse of context_analysis.CATEGORY_LABELS (label -> category key) —
# same approach services/brand_summary.py uses to map a
# ContextAnalysisItem.context display label back to its category.
_LABEL_TO_CATEGORY: dict[str, str] = {label: category for category, label in CATEGORY_LABELS.items()}

# Keyword substrings (case-insensitive) that hint a topic is already
# being discussed in cooccurrenceRanking even if contextAnalysis didn't
# surface a dedicated category for it.
_PRICING_HINT_KEYWORDS = ["price", "pricing", "cost", "料金", "プラン"]
_RELIABILITY_HINT_KEYWORDS = [
    "saas", "sla", "api", "security", "セキュリティ", "エンタープライズ", "enterprise", "導入実績",
]

_PRIORITY_RANK: dict[Priority, int] = {"high": 0, "medium": 1, "low": 2}

MAX_SUGGESTIONS = 5


def _present_categories(context_analysis: list[ContextAnalysisItem]) -> set[str]:
    return {_LABEL_TO_CATEGORY.get(item.context, "general") for item in context_analysis}


def _has_keyword_hint(cooccurrence_ranking: list[CooccurrenceKeyword], hints: list[str]) -> bool:
    if not cooccurrence_ranking:
        return False
    haystack = " ".join(keyword.keyword.lower() for keyword in cooccurrence_ranking)
    return any(hint.lower() in haystack for hint in hints)


def _pricing_suggestion(
    present: set[str], cooccurrence_ranking: list[CooccurrenceKeyword]
) -> ImprovementSuggestion | None:
    if "pricing" in present:
        return None

    has_hint = _has_keyword_hint(cooccurrence_ranking, _PRICING_HINT_KEYWORDS)
    if has_hint:
        priority: Priority = "medium"
        reason = "共起語には料金関連のキーワードが見られるものの、文脈分析では料金カテゴリとして明確に確認できないため、"
    else:
        priority = "high"
        reason = "現在の文脈分析・共起語のいずれにも料金・価格に関する言及が確認できないため、"

    return ImprovementSuggestion(
        title="料金・プラン情報の明確化",
        description=(
            f"{reason}AIに料金体系を理解されやすくするため、料金・プラン・無料/有料の違いを明確にした"
            "ページやFAQを整備することを推奨します。"
        ),
        priority=priority,
    )


def _use_case_suggestion(present: set[str]) -> ImprovementSuggestion | None:
    if "use_case" in present:
        return None
    return ImprovementSuggestion(
        title="導入事例・活用シーンの追加",
        description=(
            "現在の文脈分析では導入事例・活用シーンに関する言及が確認できないため、ブランドがどのような場面で"
            "使われるかをAIに認識されやすくする具体的な導入事例やユースケースの追加を推奨します。"
        ),
        priority="medium",
    )


def _support_suggestion(present: set[str]) -> ImprovementSuggestion | None:
    if "support" in present:
        return None
    return ImprovementSuggestion(
        title="FAQ・サポート情報の構造化",
        description=(
            "現在の文脈分析ではサポート・問い合わせに関する言及が確認できないため、サポートや問い合わせに関する"
            "情報をFAQ形式で整理し、AIが引用・要約しやすい構造にすることを推奨します。"
        ),
        priority="medium",
    )


def _reliability_suggestion(
    present: set[str], cooccurrence_ranking: list[CooccurrenceKeyword]
) -> ImprovementSuggestion | None:
    has_hint = _has_keyword_hint(cooccurrence_ranking, _RELIABILITY_HINT_KEYWORDS)
    is_present = "reliability" in present

    if is_present and not has_hint:
        return None

    if not is_present and has_hint:
        priority: Priority = "medium"
        reason = (
            "共起語にSaaS/BtoB関連のキーワードが見られる一方、文脈分析では信頼性・セキュリティのカテゴリが"
            "確認できないため、"
        )
    elif not is_present:
        priority = "medium"
        reason = "現在の文脈分析では信頼性・セキュリティに関する言及が確認できないため、"
    else:
        # Present, but a strong SaaS/BtoB signal suggests reinforcing it further is still worthwhile.
        priority = "low"
        reason = "SaaS/BtoB関連のキーワードが多く見られ、信頼性・セキュリティ訴求の重要度が高いと考えられるため、"

    return ImprovementSuggestion(
        title="信頼性・セキュリティ情報の強化",
        description=(
            f"{reason}セキュリティ、稼働率、導入実績などの情報を明確にし、AIが信頼性の高いブランドとして"
            "認識しやすくすることを推奨します。"
        ),
        priority=priority,
    )


# Thresholds for _ai_overview_reference_suggestion()'s third-party-heavy
# case — deliberately conservative (both a minimum count and a minimum
# ratio) so a single third-party reference among one or two total
# doesn't trigger it.
_THIRD_PARTY_HEAVY_MIN_COUNT = 3
_THIRD_PARTY_HEAVY_MIN_RATIO = 0.75


def _ai_overview_reference_suggestion(
    ai_overview_items: list[AIOverviewComparisonItem] | None,
) -> ImprovementSuggestion | None:
    """At most one suggestion derived from the DataForSEO-backed AI
    Overview item's ownDomainReferenced/referenceSummary (see
    services/ai_overview_provider.py) — a no-op when aiOverviewComparison
    is mock/off/unavailable, since those never set ownDomainReferenced.

    Only the first item with a judged (non-None) ownDomainReferenced is
    considered — in practice there's at most one dataforseo-derived item
    per response (see build_ai_overview_comparison), so this doesn't
    need to reconcile multiple items disagreeing with each other.
    """
    for item in ai_overview_items or []:
        if item.ownDomainReferenced is None:
            continue

        if item.ownDomainReferenced is False:
            return ImprovementSuggestion(
                title="AI Overview参照元への公式ページ掲載",
                description=(
                    "AI Overviewの参照元に自社サイトが確認できません。公式ページに、ブランド概要・"
                    "主要サービス・導入事例・料金・比較情報を明確に記載し、AIが引用しやすい構造に"
                    "整理してください。"
                ),
                priority="medium",
            )

        summary = item.referenceSummary
        if summary is not None and summary.total > 0:
            is_third_party_heavy = (
                summary.thirdParty >= _THIRD_PARTY_HEAVY_MIN_COUNT
                and summary.thirdParty / summary.total >= _THIRD_PARTY_HEAVY_MIN_RATIO
            )
            if is_third_party_heavy:
                return ImprovementSuggestion(
                    title="AI Overviewにおける第三者サイト依存への対応",
                    description=(
                        "AI Overviewでは第三者サイトの参照比率が高い可能性があります。公式情報と"
                        "第三者記事の説明にズレがないか確認してください。"
                    ),
                    priority="low",
                )

        return ImprovementSuggestion(
            title="AI Overview参照元の公式ページ更新",
            description=(
                "AI Overviewの参照元に自社サイトが含まれています。現在引用されている公式ページの"
                "内容を定期的に更新し、サービス概要・強み・比較情報をより明確にしてください。"
            ),
            priority="low",
        )

    return None


def _common_crawl_suggestion(
    common_crawl_provider: CommonCrawlProviderInfo | None,
) -> ImprovementSuggestion | None:
    """At most one suggestion derived from the Common Crawl "補完" flow's
    outcome (`meta.commonCrawlProvider`, see main.py's
    _build_common_crawl_documents() and
    docs/14_common_crawl_improvement_policy.md for the policy this
    follows). A no-op when Common Crawl is off (the user isn't using
    this feature, so surfacing a suggestion about it would be
    confusing) or when `common_crawl_provider` wasn't passed at all
    (e.g. an older caller/test).

    Gates purely on `status`, not on `documentCount` — `status="real"`
    already means "at least one Document was added" by construction
    (see CommonCrawlProviderInfo's docstring), so this doesn't need its
    own redundant document-count check; a `documentCount` of 0 alongside
    `status="real"` (which shouldn't happen today) is still treated as
    "real" here rather than silently falling back to the "unavailable"
    wording.

    Deliberately avoids any of the overstated claims
    docs/14_common_crawl_improvement_policy.md's "避けるべき表現" section
    warns against (no "AIが必ず学習している", no guarantee that an answer
    will change, no ranking-factor causation claim) — Common Crawl is
    framed as a supplementary estimate of the Web information
    environment, never as proof of what any specific LLM actually
    learned. Never includes `common_crawl_provider.reason` (a
    developer-facing status string, not meant for direct end-user
    display) or any HTML/WARC content — CommonCrawlProviderInfo has no
    field for either anyway.
    """
    if common_crawl_provider is None:
        return None

    if common_crawl_provider.status == "off":
        return None

    if common_crawl_provider.status == "real":
        return ImprovementSuggestion(
            title="Common Crawl補完で確認できる文脈の一貫性を高める",
            description=(
                "Common Crawl補完で取得したページにもブランド関連文脈が含まれています。"
                "公式サイト側では、導入事例・対象顧客・主要機能の説明を一貫して記載すると、"
                "AIに拾われる文脈を安定させやすくなります。"
            ),
            priority="medium",
        )

    # status == "unavailable"
    return ImprovementSuggestion(
        title="クロールされやすい重要ページを整備する",
        description=(
            "Common Crawl補完では十分なページを取得できませんでした。"
            "まずは公式サイト内の重要ページを明確化し、クロールされやすい構造・内部リンクを"
            "整えることを検討してください。"
        ),
        priority="low",
    )


def _risk_or_issue_suggestion(present: set[str]) -> ImprovementSuggestion | None:
    if "risk_or_issue" not in present:
        return None
    return ImprovementSuggestion(
        title="誤解されやすい表現・課題文脈の改善",
        description=(
            "文脈分析で問題・エラー・制限に関する言及（risk_or_issue）が検出されたため、該当する課題に対する"
            "解決策や補足説明を併記し、ネガティブな認識を緩和することを推奨します。"
        ),
        priority="high",
    )


def _keyword_diversity_suggestion(
    summary: BrandSummary,
    cooccurrence_ranking: list[CooccurrenceKeyword],
    context_analysis: list[ContextAnalysisItem],
) -> ImprovementSuggestion | None:
    reasons: list[str] = []
    severity: Priority = "low"

    if summary.totalMentions == 0:
        reasons.append("ブランド名の言及自体が確認できない")
        severity = "high"
    if len(context_analysis) == 0:
        reasons.append("文脈分析の結果が0件")
        severity = "high"
    elif len(context_analysis) <= 2:
        reasons.append(f"文脈分析で確認できたカテゴリが{len(context_analysis)}件と少ない")
        if severity != "high":
            severity = "medium"
    if len(cooccurrence_ranking) < 5:
        reasons.append(f"共起語ランキングが{len(cooccurrence_ranking)}件と少ない")
        if severity == "low":
            severity = "medium"
    if summary.visibilityScore < 30:
        reasons.append(f"認知スコアが{summary.visibilityScore}と低い")
        if severity != "high":
            severity = "medium"

    if not reasons:
        return None

    reason_text = "・".join(reasons) + "ため、"
    return ImprovementSuggestion(
        title="重要キーワードとの関連性強化",
        description=(
            f"{reason_text}ブランドと一緒に認識されたい機能名・業界語・用途語をページ内で自然に増やし、"
            "AIに伝わる文脈を強化することを推奨します。"
        ),
        priority=severity,
    )


def _cap_priority_for_development_sample_only(
    priority: Priority, source_types: list[str] | None
) -> Priority:
    """development_sample以外の裏付け（実サイト・ユーザー入力）が一切ない
    場合、"high"は根拠として強すぎるため"medium"へ抑える。"""
    if source_types == ["development_sample"] and priority == "high":
        return "medium"
    return priority


def build_improvement_suggestions(
    brand_name: str,
    summary: BrandSummary,
    cooccurrence_ranking: list[CooccurrenceKeyword],
    context_analysis: list[ContextAnalysisItem],
    document_count: int | None = None,
    source_types: list[str] | None = None,
    ai_overview_items: list[AIOverviewComparisonItem] | None = None,
    common_crawl_provider: CommonCrawlProviderInfo | None = None,
) -> list[ImprovementSuggestion]:
    """Builds ImprovementSuggestion[] from cooccurrenceRanking/
    contextAnalysis/summary using simple, rule-based conditions (see
    module docstring), plus at most one suggestion derived from
    `ai_overview_items` (see _ai_overview_reference_suggestion — a
    no-op unless aiOverviewComparison actually ran in "dataforseo" mode
    and set ownDomainReferenced), and at most one suggestion derived
    from `common_crawl_provider` (see _common_crawl_suggestion — a
    no-op when Common Crawl is off or wasn't passed at all). Not a
    substitute for a human SEO/LLMO judgment call — this is MVP-grade
    triage meant to explain *why* each suggestion was raised, not to
    prescribe a definitive action plan.

    Always returns at least one suggestion (a low-priority fallback if
    no rule was triggered), so callers don't need to special-case an
    empty list themselves. Whether the section is "real"/"unavailable"
    overall (e.g. when every url in `urls` failed to fetch) is decided
    by main.py, mirroring contextAnalysis/summary.
    """
    del brand_name  # not needed by any rule below; kept for signature parity with the other Analyzer functions

    present = _present_categories(context_analysis)

    candidates = [
        _pricing_suggestion(present, cooccurrence_ranking),
        _use_case_suggestion(present),
        _support_suggestion(present),
        _reliability_suggestion(present, cooccurrence_ranking),
        _risk_or_issue_suggestion(present),
        _keyword_diversity_suggestion(summary, cooccurrence_ranking, context_analysis),
        _ai_overview_reference_suggestion(ai_overview_items),
        _common_crawl_suggestion(common_crawl_provider),
    ]
    suggestions = [item for item in candidates if item is not None]

    if not suggestions:
        note = (
            f"（解析対象のDocumentは{document_count}件でした）" if document_count is not None else ""
        )
        return [
            ImprovementSuggestion(
                title="改善提案を作るための十分な文脈がありません",
                description=(
                    "現在の分析結果からは具体的な改善提案を生成するための十分な文脈が得られませんでした。"
                    f"documentsやurlsを追加すると、より具体的な提案が可能になります{note}。"
                ),
                priority="low",
            )
        ]

    suggestions = [
        suggestion.model_copy(
            update={"priority": _cap_priority_for_development_sample_only(suggestion.priority, source_types)}
        )
        for suggestion in suggestions
    ]

    suggestions.sort(key=lambda suggestion: _PRIORITY_RANK[suggestion.priority])

    return suggestions[:MAX_SUGGESTIONS]
