"""Minimal Japanese co-occurrence keyword extraction.

Given a brand name and a list of documents (plain Japanese text), this
finds words that appear near the brand name and ranks them by
frequency. This is intentionally simple (character-window + POS
filtering, no real relevance scoring) — see docs/07_decisions.md for
why Janome was chosen and what a future iteration might improve.
"""

from collections import Counter

from janome.tokenizer import Tokenizer

from models import CooccurrenceKeyword, Document

# How many characters before/after each brand name occurrence to scan
# for candidate keywords. Character-based (not token-based) because a
# brand name isn't guaranteed to tokenize as a single, cleanly
# delimited token.
WINDOW_CHARS = 20

TOP_N = 10

# Only keep nouns, and only "content" noun subcategories. This
# excludes 助詞 (particles), 助動詞 (auxiliary verbs), and 記号
# (symbols) simply by never being 名詞 in the first place, and also
# drops noun subcategories that are themselves too generic to be
# useful keywords (代名詞 pronouns like これ/それ, 非自立 dependent
# nouns like こと/もの/ため/よう, 接尾 suffixes like さん/たち, and
# 数 bare numbers).
ALLOWED_NOUN_SUBCATEGORIES = {"一般", "固有名詞", "サ変接続", "形容動詞語幹"}

# Extra lexical stopwords, as a second safety net for generic words
# that could still slip through the POS filter above.
STOPWORDS = {
    "これ", "それ", "あれ", "ここ", "そこ", "あそこ",
    "こと", "もの", "とき", "ところ", "ため", "よう", "そう", "うち", "ほう",
    "さん", "たち", "など", "そちら", "こちら", "あちら",
}

MIN_KEYWORD_LENGTH = 2

_tokenizer = Tokenizer()


def _extract_windows(text: str, brand_name: str) -> list[str]:
    """Returns the text slices before/after each occurrence of brand_name.

    The brand name itself is never included in a returned slice, so it
    cannot be re-tokenized back into a candidate keyword.
    """
    windows: list[str] = []
    search_start = 0
    while True:
        idx = text.find(brand_name, search_start)
        if idx == -1:
            break

        before = text[max(0, idx - WINDOW_CHARS):idx]
        after_start = idx + len(brand_name)
        after = text[after_start:after_start + WINDOW_CHARS]

        if before:
            windows.append(before)
        if after:
            windows.append(after)

        search_start = after_start

    return windows


def _is_candidate_keyword(surface: str, part_of_speech: str, brand_name: str) -> bool:
    pos_parts = part_of_speech.split(",")
    top = pos_parts[0]
    sub = pos_parts[1] if len(pos_parts) > 1 else ""

    if top != "名詞":
        return False
    if sub not in ALLOWED_NOUN_SUBCATEGORIES:
        return False
    if len(surface) < MIN_KEYWORD_LENGTH:
        return False
    if surface in STOPWORDS:
        return False
    if surface.lower() == brand_name.lower():
        return False

    return True


def compute_cooccurrence_ranking(
    brand_name: str,
    documents: list[str],
    top_n: int = TOP_N,
) -> list[CooccurrenceKeyword]:
    """Counts words appearing near brand_name across documents.

    Blank/whitespace-only documents are skipped; an empty or
    all-blank `documents` list simply yields an empty ranking rather
    than raising.
    """
    counts: Counter[str] = Counter()

    for document in documents:
        if not document or not document.strip():
            continue

        for window in _extract_windows(document, brand_name):
            for token in _tokenizer.tokenize(window):
                if _is_candidate_keyword(token.surface, token.part_of_speech, brand_name):
                    counts[token.surface] += 1

    return [
        # Real "up/down/flat" trend requires comparing against a
        # previous analysis run, which isn't implemented yet
        # (docs/05_tasks.md Phase 4.2) — default to "flat" for now.
        CooccurrenceKeyword(keyword=keyword, count=count, trend="flat")
        for keyword, count in counts.most_common(top_n)
    ]


def compute_cooccurrence_ranking_from_documents(
    brand_name: str,
    documents: list[Document],
    top_n: int = TOP_N,
) -> list[CooccurrenceKeyword]:
    """Thin Document[]-based adapter over compute_cooccurrence_ranking().

    Extracts .text from each Document and delegates — the extraction/
    POS-filter logic itself is untouched. See docs/11_architecture_v1.md
    "4. Document Pipeline" ("Analyzer" reads from Document[]).
    """
    return compute_cooccurrence_ranking(
        brand_name, [document.text for document in documents], top_n
    )
