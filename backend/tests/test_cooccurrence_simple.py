import pytest

from models import Document
from services.cooccurrence import (
    _simple_tokenize_candidates,
    compute_cooccurrence_ranking,
    compute_cooccurrence_ranking_from_documents,
    is_low_value_cooccurrence_term,
)


@pytest.fixture(autouse=True)
def _default_tokenizer_mode(monkeypatch):
    """These tests exercise the production default ("simple") regex
    tokenizer explicitly, regardless of whatever TOKENIZER_MODE
    happens to be set to in the environment pytest runs in.
    """
    monkeypatch.delenv("TOKENIZER_MODE", raising=False)


def test_simple_tokenizer_extracts_japanese_tokens():
    tokens = _simple_tokenize_candidates("料金プランについて教えてください", "OpenAI")

    assert "料金" in tokens
    assert "プラン" in tokens


def test_simple_tokenizer_extracts_english_alphanumeric_tokens():
    tokens = _simple_tokenize_candidates(
        "Acme provides API access and Cloud99 hosting", "Acme"
    )

    assert "API" in tokens
    assert "Cloud99" in tokens


def test_simple_tokenizer_excludes_url_fragments_and_short_tokens():
    tokens = _simple_tokenize_candidates("visit https www acme com a b", "Acme")

    assert not set(tokens) & {"https", "www", "com", "a", "b"}


def test_simple_tokenizer_excludes_brand_name_itself():
    tokens = _simple_tokenize_candidates("Acmeについて教えてください", "Acme")

    assert "Acme" not in tokens
    assert "acme" not in {t.lower() for t in tokens}


def test_compute_cooccurrence_ranking_is_not_empty_with_simple_tokenizer():
    ranking = compute_cooccurrence_ranking(
        "OpenAI",
        ["OpenAIは料金プランが分かりやすく、導入事例も豊富だと評判です。"],
    )

    assert len(ranking) > 0
    keywords = {kw.keyword for kw in ranking}
    assert {"料金", "プラン"} <= keywords


def test_simple_tokenizer_excludes_short_english_noise_words():
    tokens = _simple_tokenize_candidates("on to in of for and or the with nd", "Acme")

    assert not set(t.lower() for t in tokens) & {
        "on", "to", "in", "of", "for", "and", "or", "the", "with", "nd",
    }


def test_simple_tokenizer_keeps_useful_alphanumeric_tokens():
    tokens = _simple_tokenize_candidates("check out our API and Cloud99 plan", "Acme")

    assert "API" in tokens
    assert "Cloud99" in tokens


def test_simple_tokenizer_excludes_two_letter_ascii_tokens_like_ai():
    # A 2-letter ASCII token is swept up as noise even when it's a
    # real acronym (e.g. "AI") — accepted as a known limitation, see
    # MIN_ASCII_KEYWORD_LENGTH in services/cooccurrence.py.
    tokens = _simple_tokenize_candidates("our AI product", "Acme")

    assert "AI" not in tokens


def test_simple_tokenizer_keeps_japanese_multichar_tokens():
    tokens = _simple_tokenize_candidates(
        "導入事例についてサポート体制も評判です", "Acme"
    )

    assert "導入事例" in tokens
    assert "サポート" in tokens


def test_compute_cooccurrence_ranking_extends_window_to_avoid_truncated_ascii_word():
    # Without extending the window past WINDOW_CHARS, the hard 20-char
    # cut lands inside "seconds", producing a "seco" fragment instead
    # of the real word — the exact class of noise (e.g. "nd") observed
    # from real pages like vercel.com/docs.
    text = "Acme " + "a" * 14 + " " + "seconds"

    ranking = compute_cooccurrence_ranking("Acme", [text])
    keywords = {kw.keyword for kw in ranking}

    assert "seco" not in keywords
    assert "seconds" in keywords


def test_compute_cooccurrence_ranking_not_empty_for_realistic_english_page_text():
    text = (
        "Acme helps teams deploy applications to the cloud on a global "
        "network, with fast previews and instant rollbacks for every project."
    )

    ranking = compute_cooccurrence_ranking("Acme", [text])

    assert len(ranking) > 0


# --- noise filter: is_low_value_cooccurrence_term() -------------------------
# Added 2026-07-28 (fix/cooccurrence-noise-filter) after enabling Common
# Crawl補完 in a real environment surfaced low-value fragments like
# "には"/"くことが"/"しくなる" as top-ranked "keywords" — see
# docs/05_tasks.md.


def test_is_low_value_excludes_reported_noise_fragments():
    for term in ("には", "くことが", "しくなる", "こと", "ことが", "ことは", "では"):
        assert is_low_value_cooccurrence_term(term), term


def test_is_low_value_keeps_meaningful_multichar_words():
    for term in (
        "サイト", "デジタル", "自治体", "導入事例",
        "グループウェア", "クラウド", "業務改善", "チームワーク",
    ):
        assert not is_low_value_cooccurrence_term(term), term


def test_is_low_value_excludes_longer_tokens_ending_in_a_noise_suffix():
    # A single unbroken hiragana run (see _split_japanese_run) can
    # produce a longer noisy token than any fixed stopword set would
    # list explicitly — this must still be caught via NOISE_SUFFIXES.
    assert is_low_value_cooccurrence_term("できることが")
    assert is_low_value_cooccurrence_term("あたらしくなる")


def test_is_low_value_does_not_flag_ascii_keywords():
    assert not is_low_value_cooccurrence_term("API")
    assert not is_low_value_cooccurrence_term("Cloud99")


def test_is_low_value_handles_empty_and_whitespace_input_without_raising():
    assert is_low_value_cooccurrence_term("") is True
    assert is_low_value_cooccurrence_term("   ") is True


def test_simple_tokenizer_excludes_niha_particle_fragment():
    tokens = _simple_tokenize_candidates("Acmeのサイトには便利な機能があります", "Acme")

    assert "には" not in tokens


def test_simple_tokenizer_excludes_kukotoga_and_shikunaru_fragments():
    tokens = _simple_tokenize_candidates(
        "Acmeを導入すると業務改善が楽しくなることが多いです", "Acme"
    )

    assert "くことが" not in tokens
    assert "しくなる" not in tokens
    assert "こと" not in tokens
    assert "ことが" not in tokens


def test_simple_tokenizer_keeps_meaningful_words_alongside_noise():
    tokens = _simple_tokenize_candidates(
        "Acmeのグループウェアにはクラウド型の導入事例が豊富で、"
        "デジタル化やサイト運営の業務改善に役立つチームワーク支援があります",
        "Acme",
    )

    for keyword in (
        "サイト", "デジタル", "導入事例",
        "グループウェア", "クラウド", "業務改善", "チームワーク",
    ):
        assert keyword in tokens, keyword

    for noise in ("には", "こと", "ことが"):
        assert noise not in tokens, noise


def test_compute_cooccurrence_ranking_excludes_noise_from_messy_html_like_text():
    # Approximates the kind of run-on, lightly-punctuated text Common
    # Crawl-sourced HTML can produce after cleaning (see
    # services/document_cleaner.py) — messier sentence boundaries than
    # the curated development-sample text, which is what originally
    # surfaced this noise in a real environment.
    text = (
        "サイボウズにはグループウェアの導入事例が豊富にあり"
        "業務改善が楽しくなることが多いですデジタル化を進めることができ"
        "サイト運営も楽になります"
    )

    ranking = compute_cooccurrence_ranking("サイボウズ", [text], top_n=20)
    keywords = {kw.keyword for kw in ranking}

    assert not keywords & {"には", "くことが", "しくなる", "こと", "ことが", "では"}
    assert {"グループウェア", "導入事例"} & keywords


def test_compute_cooccurrence_ranking_from_common_crawl_document_uses_same_filter():
    # Common Crawl由来Document (sourceType="common_crawl") must go
    # through the exact same filtering as any other Document — no
    # Common Crawl-specific branch exists in this module at all.
    document = Document(
        id="doc-1",
        sourceType="common_crawl",
        fetchedAt="2026-07-28T00:00:00+00:00",
        text=(
            "サイボウズにはグループウェアの導入事例が豊富にあり"
            "業務改善が楽しくなることが多いです"
        ),
    )

    ranking = compute_cooccurrence_ranking_from_documents("サイボウズ", [document], top_n=20)
    keywords = {kw.keyword for kw in ranking}

    assert not keywords & {"には", "くことが", "しくなる", "こと", "ことが"}
    assert "グループウェア" in keywords
