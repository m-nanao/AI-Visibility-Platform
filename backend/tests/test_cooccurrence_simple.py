import pytest

from services.cooccurrence import _simple_tokenize_candidates, compute_cooccurrence_ranking


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
