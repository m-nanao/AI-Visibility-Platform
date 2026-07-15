import subprocess
import sys
from pathlib import Path

import pytest

from models import Document
from services.cooccurrence import (
    _get_tokenizer,
    compute_cooccurrence_ranking,
    compute_cooccurrence_ranking_from_documents,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _use_janome_tokenizer(monkeypatch):
    """This file specifically tests Janome's POS-filtered extraction
    (the original tokenizer, still available but no longer the
    default — see docs/07_decisions.md and the module docstring in
    services/cooccurrence.py). The lightweight regex tokenizer that IS
    the production default has its own tests in
    tests/test_cooccurrence_simple.py.
    """
    monkeypatch.setenv("TOKENIZER_MODE", "janome")


def _make_document(text: str) -> Document:
    return Document(
        id="doc-1",
        sourceType="user_provided",
        fetchedAt="2026-07-15T00:00:00+00:00",
        text=text,
    )


def test_extracts_expected_keywords_near_brand_name():
    ranking = compute_cooccurrence_ranking(
        "OpenAI",
        ["OpenAIは料金プランが分かりやすく、導入事例も豊富です。"],
    )
    keywords = {kw.keyword for kw in ranking}

    assert {"料金", "プラン", "導入", "事例"} <= keywords


def test_excludes_brand_name_itself():
    ranking = compute_cooccurrence_ranking(
        "OpenAI",
        ["OpenAIについて、OpenAIはとても人気です。"],
    )
    keywords = {kw.keyword for kw in ranking}

    assert "OpenAI" not in keywords
    assert "openai" not in {k.lower() for k in keywords}


def test_empty_documents_list_does_not_raise():
    assert compute_cooccurrence_ranking("OpenAI", []) == []


def test_blank_documents_do_not_raise():
    assert compute_cooccurrence_ranking("OpenAI", ["", "   ", "\n"]) == []


def test_excludes_particles_and_symbols():
    ranking = compute_cooccurrence_ranking(
        "OpenAI",
        ["OpenAIは、料金プランがとても分かりやすいです。"],
    )
    keywords = {kw.keyword for kw in ranking}

    # 助詞 (particles), 記号 (symbols), and 助動詞 (auxiliary verb) must
    # never show up as keywords.
    assert not keywords & {"は", "、", "が", "です", "。"}
    assert {"料金", "プラン"} <= keywords


def test_counts_accumulate_across_documents():
    ranking = compute_cooccurrence_ranking(
        "OpenAI",
        [
            "OpenAIの料金プランについて教えてください。",
            "OpenAIの料金プランはとても安いです。",
        ],
    )
    counts = {kw.keyword: kw.count for kw in ranking}

    assert counts["料金"] == 2
    assert counts["プラン"] == 2


def test_ranking_is_sorted_by_count_descending_and_capped():
    documents = ["OpenAIの料金プランについて教えてください。"] * 5 + [
        "OpenAIの導入事例は一件だけです。",
    ]

    ranking = compute_cooccurrence_ranking("OpenAI", documents, top_n=2)

    assert len(ranking) == 2
    assert ranking[0].count >= ranking[1].count
    assert ranking[0].keyword in {"料金", "プラン"}


def test_compute_cooccurrence_ranking_from_documents_matches_text_based_version():
    text = "OpenAIは料金プランが分かりやすく、導入事例も豊富です。"
    documents = [_make_document(text)]

    from_documents = compute_cooccurrence_ranking_from_documents("OpenAI", documents)
    from_text = compute_cooccurrence_ranking("OpenAI", [text])

    assert from_documents == from_text


def test_compute_cooccurrence_ranking_from_documents_handles_empty_list():
    assert compute_cooccurrence_ranking_from_documents("OpenAI", []) == []


def test_importing_cooccurrence_module_does_not_construct_tokenizer():
    """Guards against a regression back to a module-level Tokenizer().

    Run in a fresh subprocess (not this test process, which may have
    already called compute_cooccurrence_ranking via other tests) so
    the check reflects what actually happens at FastAPI startup, when
    `import services.cooccurrence` is the only thing that has run.
    """
    script = (
        "import sys; "
        "import services.cooccurrence; "
        "assert 'janome.tokenizer' not in sys.modules, "
        "'importing services.cooccurrence must not import janome.tokenizer'"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        check=True,
    )


def test_get_tokenizer_is_cached_across_calls():
    assert _get_tokenizer() is _get_tokenizer()
