"""Document text normalization: Unicode/whitespace/invisible-character
cleanup applied before analysis, regardless of where the text came from
(Cleaner-extracted HTML body text, or a caller-supplied `documents`
string).

This is the Pipeline's "Normalizer" stage (see docs/11_architecture_v1.md
"4. Document Pipeline"). It sits between Cleaner and Analyzer:

- It does not decide *what* text to look at — extracting body text from
  HTML is document_cleaner.py's job; accepting a caller's raw string is
  main.py's job. This module only reshapes text it's handed.
- It does not tokenize, apply stopwords, or do any co-occurrence
  logic — that's services/cooccurrence.py's Analyzer job.

Deliberately lightweight: no external dependencies, no dictionary-based
normalization (e.g. old/new kanji form unification, spelling-variant
unification), and no transformation strong enough to change a text's
meaning. Render free-tier friendly.
"""

import re
import unicodedata

# Zero-width/formatting characters that carry no analyzable meaning but
# can silently break word boundaries or hide inside otherwise-normal
# text (common when copy-pasted from a web page). None of these have a
# Unicode compatibility decomposition, so NFKC normalization alone
# would not remove them.
_INVISIBLE_CHARS_RE = re.compile(
    "["
    "​"  # zero width space
    "‌"  # zero width non-joiner
    "‍"  # zero width joiner
    "﻿"  # BOM / zero width no-break space
    "]"
)

# C0/C1 control characters, excluding \t/\n/\r — those are handled by
# the whitespace cleanup below instead of being stripped outright.
_CONTROL_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Runs of 2+ horizontal whitespace (after tabs are folded to spaces
# below) collapse to a single space. A single space is left alone —
# e.g. "料金 プラン" must not become "料金プラン".
_MULTIPLE_SPACES_RE = re.compile(r" {2,}")

# 3+ consecutive newlines (2+ blank lines) collapse down to a single
# blank line (2 newlines).
_MULTIPLE_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Light cleanup of *excessive* repeated punctuation (e.g. "!!!!!!" from
# a scraped marketing banner). Threshold is deliberately conservative
# (4+ repeats, collapsed to 3) so normal, meaningful punctuation runs
# like an ellipsis "..." or emphasis "!!!"/"???" (3 characters) are
# left untouched.
_EXCESSIVE_PUNCTUATION_RE = re.compile(r"([!?。、,.!?…\-~〜])\1{3,}")


def normalize_text(text: str) -> str:
    """Normalizes analyzable text: Unicode form, invisible characters,
    and whitespace. Does not remove or rewrite URLs/email addresses,
    and does not attempt dictionary-based Japanese normalization
    (spelling variants, old/new kanji forms) — see module docstring.

    Safe on empty/whitespace-only input (returns "" rather than
    raising).
    """
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # NFKC folds full-width ASCII (e.g. "ＡＩ１２３" -> "AI123"), half-width
    # katakana, and several other space/punctuation variants (e.g. the
    # full-width ideographic space U+3000) into their standard forms.
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = _INVISIBLE_CHARS_RE.sub("", normalized)
    normalized = _CONTROL_CHARS_RE.sub("", normalized)
    normalized = normalized.replace("\t", " ")
    normalized = _MULTIPLE_SPACES_RE.sub(" ", normalized)
    normalized = _EXCESSIVE_PUNCTUATION_RE.sub(lambda m: m.group(1) * 3, normalized)

    lines = [line.strip() for line in normalized.split("\n")]
    normalized = "\n".join(lines)
    normalized = _MULTIPLE_BLANK_LINES_RE.sub("\n\n", normalized)

    return normalized.strip()
