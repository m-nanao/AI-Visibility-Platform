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
