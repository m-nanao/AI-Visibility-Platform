"""Minimal co-occurrence keyword extraction.

Given a brand name and a list of documents (plain text, mostly
Japanese), this finds words that appear near the brand name and ranks
them by frequency. This is intentionally simple (character-window +
lexical filtering, no real relevance scoring) — see docs/07_decisions.md
for why Janome was originally chosen and what a future iteration might
improve.

Two tokenizers are available, selected via the `TOKENIZER_MODE`
environment variable:

- `simple` (default): a regex-based tokenizer with no external
  dictionary. Chosen as the default because Janome's dictionary load
  is expensive enough (100MB+) to push a Render free-tier instance
  (512MB) into an out-of-memory crash or timeout during `/analyze` —
  MVP prioritizes the confirmation environment staying up over
  extraction accuracy (see docs/07_decisions.md, and the
  fix/render-analyze-memory task notes in docs/05_tasks.md).
- `janome`: the original POS-filtered morphological analyzer. Opt-in
  only (`TOKENIZER_MODE=janome`) for environments with enough memory
  headroom.
"""

import os
import re
from collections import Counter
from functools import lru_cache
from itertools import groupby

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
# that could still slip through the POS filter above (Janome mode) or
# that the simple tokenizer has no POS info to filter at all (simple
# mode — copula/auxiliary forms like です/ます would otherwise show up
# as "keywords" next to every brand name).
STOPWORDS = {
    "これ", "それ", "あれ", "ここ", "そこ", "あそこ",
    "こと", "もの", "とき", "ところ", "ため", "よう", "そう", "うち", "ほう",
    "さん", "たち", "など", "そちら", "こちら", "あちら",
    "です", "ます", "ました", "ください", "という", "して", "した",
    "ある", "あります", "できる", "なる",
}

MIN_KEYWORD_LENGTH = 2

# Stricter minimum length for ASCII tokens only, in the simple
# tokenizer. English function words this short are almost always noise
# ("on", "to", "nd") rather than meaningful keywords — a 2-letter
# acronym like "AI" is deliberately swept up in this too (see
# docs/07_decisions.md); a real brand/product term is essentially
# never this short. Japanese keeps MIN_KEYWORD_LENGTH (2) — this only
# raises the bar for the `[A-Za-z0-9]+` half of _SIMPLE_TOKEN_RE.
MIN_ASCII_KEYWORD_LENGTH = 3

# Extra stopwords for the "simple" tokenizer only: common English
# function words and URL/markup fragments that can otherwise slip
# through as candidate keywords, since the simple tokenizer has no
# part-of-speech info to filter on. Includes 3+ letter function words
# that MIN_ASCII_KEYWORD_LENGTH alone wouldn't catch (e.g. "the", "and").
SIMPLE_MODE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "com", "for",
    "from", "has", "have", "html", "http", "https", "in", "is", "it",
    "net", "not", "on", "or", "org", "our", "that", "the", "this",
    "to", "was", "were", "with", "www", "you", "your",
}

# Matches runs of ASCII alphanumerics (English/numeric "words") or runs
# of Japanese characters (hiragana, katakana incl. the prolonged sound
# mark U+30FC, and CJK kanji). No dictionary lookup, so this is far
# cheaper than Janome. Japanese runs are further split at
# hiragana/katakana/kanji boundaries below (_split_japanese_run) as a
# cheap proxy for word boundaries — e.g. "料金プランが" (kanji + katakana
# + hiragana) becomes "料金" / "プラン" / "が", without needing a
# dictionary. This still can't split a run of same-type characters
# (e.g. a 4-kanji compound stays one token) — see the module docstring.
_SIMPLE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[぀-ヿ一-鿿]+")

_HIRAGANA_RANGE = range(0x3040, 0x30A0)
_KATAKANA_RANGE = range(0x30A0, 0x3100)


def _char_type(ch: str) -> str:
    code = ord(ch)
    if code in _HIRAGANA_RANGE:
        return "hiragana"
    if code in _KATAKANA_RANGE:
        return "katakana"
    return "kanji"


def _split_japanese_run(run: str) -> list[str]:
    return ["".join(chars) for _, chars in groupby(run, key=_char_type)]


def _tokenizer_mode() -> str:
    return os.environ.get("TOKENIZER_MODE", "simple").strip().lower()


def get_tokenizer_mode() -> str:
    """Public accessor for the active tokenizer mode ("simple"/"janome").

    Used by main.py's /analyze diagnostic logging so Render logs show
    which tokenizer actually ran, without main.py reaching into this
    module's private `_tokenizer_mode()`.
    """
    return _tokenizer_mode()


@lru_cache(maxsize=1)
def _get_tokenizer():
    """Constructs Janome's Tokenizer (and loads its dictionary) lazily.

    Janome's dictionary load is expensive enough to push a Render free
    tier instance (512MB) over its memory limit if it happens at
    import time — so this must only run on first actual use (the
    first /analyze call), never as a side effect of importing this
    module during FastAPI startup.
    """
    from janome.tokenizer import Tokenizer

    return Tokenizer()


# Extra character budget for extending a simple-mode window past
# WINDOW_CHARS so an ASCII word is never cut mid-word (e.g. "second"
# -> "nd"). Capped to avoid runaway growth on pathological input (a
# long run of alnum characters with no separators).
MAX_BOUNDARY_EXTENSION = 30


def _is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _extend_window_start(text: str, start: int) -> int:
    """Moves `start` left while it sits in the middle of an ASCII
    alnum run, so the word at the window's left edge isn't cut in
    half. Bounded by MAX_BOUNDARY_EXTENSION.
    """
    extended = 0
    while (
        start > 0
        and extended < MAX_BOUNDARY_EXTENSION
        and _is_ascii_alnum(text[start - 1])
        and _is_ascii_alnum(text[start])
    ):
        start -= 1
        extended += 1
    return start


def _extend_window_end(text: str, end: int) -> int:
    """Mirror of _extend_window_start for a window's right edge."""
    extended = 0
    while (
        end < len(text)
        and extended < MAX_BOUNDARY_EXTENSION
        and _is_ascii_alnum(text[end - 1])
        and _is_ascii_alnum(text[end])
    ):
        end += 1
        extended += 1
    return end


def _extract_windows(
    text: str, brand_name: str, extend_ascii_boundary: bool = False
) -> list[str]:
    """Returns the text slices before/after each occurrence of brand_name.

    The brand name itself is never included in a returned slice, so it
    cannot be re-tokenized back into a candidate keyword.

    extend_ascii_boundary=True (used by the simple tokenizer) extends
    a window's outer edge past WINDOW_CHARS whenever the hard cut would
    otherwise land mid-word in an ASCII run — see _extend_window_start/
    _extend_window_end. Janome mode leaves this False so its existing,
    already-tested window slicing is completely unchanged (a real
    morphological analyzer handles a partial token reasonably on its
    own, so this isn't needed there).
    """
    windows: list[str] = []
    search_start = 0
    while True:
        idx = text.find(brand_name, search_start)
        if idx == -1:
            break

        before_start = max(0, idx - WINDOW_CHARS)
        after_start = idx + len(brand_name)
        after_end = after_start + WINDOW_CHARS

        if extend_ascii_boundary:
            before_start = _extend_window_start(text, before_start)
            after_end = _extend_window_end(text, after_end)

        before = text[before_start:idx]
        after = text[after_start:after_end]

        if before:
            windows.append(before)
        if after:
            windows.append(after)

        search_start = after_start

    return windows


def _is_janome_candidate_keyword(surface: str, part_of_speech: str, brand_name: str) -> bool:
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


def _is_simple_candidate_keyword(token: str, brand_name: str) -> bool:
    if token.isascii():
        if len(token) < MIN_ASCII_KEYWORD_LENGTH:
            return False
    elif len(token) < MIN_KEYWORD_LENGTH:
        return False
    if token.isdigit():
        return False
    if token in STOPWORDS:
        return False
    if token.lower() in SIMPLE_MODE_STOPWORDS:
        return False
    if token.lower() == brand_name.lower():
        return False

    return True


def _simple_tokenize_candidates(window: str, brand_name: str) -> list[str]:
    """Regex + character-type based candidate keyword extraction.

    Not a real morphological analyzer: a run of same-type characters
    (e.g. 4 kanji in a row) is kept whole rather than split into
    words, so multi-word compounds can show up as a single "keyword".
    Acceptable for MVP — see the module docstring for why this is the
    default over Janome.
    """
    tokens: list[str] = []
    for run in _SIMPLE_TOKEN_RE.findall(window):
        if run[0].isascii():
            tokens.append(run)
        else:
            tokens.extend(_split_japanese_run(run))

    return [token for token in tokens if _is_simple_candidate_keyword(token, brand_name)]


def compute_cooccurrence_ranking(
    brand_name: str,
    documents: list[str],
    top_n: int = TOP_N,
) -> list[CooccurrenceKeyword]:
    """Counts words appearing near brand_name across documents.

    Blank/whitespace-only documents are skipped; an empty or
    all-blank `documents` list simply yields an empty ranking rather
    than raising.

    Uses the "simple" (regex-based) tokenizer by default, or Janome if
    `TOKENIZER_MODE=janome` is set — see the module docstring.
    """
    counts: Counter[str] = Counter()
    use_janome = _tokenizer_mode() == "janome"

    for document in documents:
        if not document or not document.strip():
            continue

        for window in _extract_windows(
            document, brand_name, extend_ascii_boundary=not use_janome
        ):
            if use_janome:
                for token in _get_tokenizer().tokenize(window):
                    if _is_janome_candidate_keyword(token.surface, token.part_of_speech, brand_name):
                        counts[token.surface] += 1
            else:
                for token in _simple_tokenize_candidates(window, brand_name):
                    counts[token] += 1

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
