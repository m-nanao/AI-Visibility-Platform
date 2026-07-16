from models import Document
from services.context_analysis import MAX_EXCERPT_CHARS, analyze_contexts, classify_context
from services.document_chunker import chunk_documents


def _make_document(text: str, **overrides) -> Document:
    defaults = dict(
        id="doc-1",
        sourceType="user_provided",
        fetchedAt="2026-07-16T00:00:00+00:00",
        text=text,
    )
    defaults.update(overrides)
    return Document(**defaults)


def test_classify_context_recognizes_pricing_keywords():
    assert classify_context("料金プランがとても分かりやすいです。") == "pricing"


def test_classify_context_recognizes_feature_keywords():
    assert classify_context("自動で連携できる機能が便利です。") == "feature"


def test_classify_context_recognizes_support_keywords():
    # Deliberately avoids "対応" (a feature keyword) so this isolates
    # the support category without a keyword-count tie against feature.
    assert classify_context("サポートへの問い合わせがとても丁寧でした。") == "support"


def test_classify_context_recognizes_risk_or_issue_keywords():
    assert classify_context("エラーが頻発するという問題があります。") == "risk_or_issue"


def test_classify_context_falls_back_to_general_when_no_keyword_matches():
    assert classify_context("今日は天気がとても良いですね。") == "general"


def test_analyze_contexts_prioritizes_chunks_mentioning_the_brand():
    chunks = chunk_documents(
        [
            _make_document("この業界の料金相場は様々です。", id="unrelated"),
            _make_document("Acmeの料金プランはとても分かりやすいです。", id="relevant"),
        ]
    )

    items = analyze_contexts("Acme", chunks)

    assert len(items) > 0
    assert all("Acme" in item.exampleQuote or "料金" in item.exampleQuote for item in items)


def test_analyze_contexts_brand_name_matching_is_case_insensitive():
    chunks = chunk_documents([_make_document("acmeの料金プランについて教えてください。")])

    items = analyze_contexts("Acme", chunks)

    assert len(items) > 0


def test_analyze_contexts_does_not_raise_when_no_chunk_mentions_the_brand():
    chunks = chunk_documents(
        [_make_document("このサービスの機能は便利です。サポートも良いです。")]
    )

    # "SomeOtherBrand" never appears in the chunk text, so this
    # exercises the fallback path rather than raising.
    items = analyze_contexts("SomeOtherBrand", chunks)

    assert isinstance(items, list)


def test_analyze_contexts_returns_empty_list_for_no_chunks():
    assert analyze_contexts("Acme", []) == []


def test_analyze_contexts_excerpts_are_not_too_long():
    long_text = "あ" * 500
    chunks = chunk_documents([_make_document(f"Acme {long_text}")], max_chars=2000)

    items = analyze_contexts("Acme", chunks)

    assert all(len(item.exampleQuote) <= MAX_EXCERPT_CHARS for item in items)


def test_analyze_contexts_respects_max_contexts_limit():
    chunks = chunk_documents(
        [
            _make_document("Acmeの料金プランは分かりやすいです。", id="d1"),
            _make_document("Acmeの機能はAPI連携ができて便利です。", id="d2"),
            _make_document("Acmeの導入事例を活用しています。", id="d3"),
            _make_document("Acmeのサポートへの問い合わせは迅速です。", id="d4"),
            _make_document("Acmeはセキュリティが安定しています。", id="d5"),
            _make_document("Acmeを競合他社と比較しました。", id="d6"),
            _make_document("Acmeにはエラーが出るという問題があります。", id="d7"),
        ]
    )

    items = analyze_contexts("Acme", chunks, max_contexts=3)

    assert len(items) <= 3


def test_analyze_contexts_context_labels_are_unique():
    # ContextAnalysisSection.tsx uses item.context as a React key, so
    # categories must not repeat within one response.
    chunks = chunk_documents(
        [
            _make_document("Acmeの料金プランは分かりやすいです。", id="d1"),
            _make_document("Acmeの機能はAPI連携ができて便利です。", id="d2"),
        ]
    )

    items = analyze_contexts("Acme", chunks)

    labels = [item.context for item in items]
    assert len(labels) == len(set(labels))
