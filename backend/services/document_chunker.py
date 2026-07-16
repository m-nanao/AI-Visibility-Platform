"""Splits Document.text into smaller DocumentChunk[] units.

This is the Pipeline's "Chunker" stage (see docs/11_architecture_v1.md
"4. Document Pipeline"), sitting after Normalizer and before any future
Embedding/context-analysis logic:

- It does not decide what a Document's text contains — that's the
  Provider/Cleaner/Normalizer stages' job. This module only splits
  already-normalized text.
- It does not tokenize, embed, or analyze chunk content in any way —
  that's a future Analyzer concern. Today, nothing consumes
  DocumentChunk[] yet; compute_cooccurrence_ranking_from_documents()
  still reads whole Document.text directly.

Deliberately lightweight: stdlib only, no new dependencies. Splitting
prefers natural boundaries (paragraph breaks, line breaks, sentence
punctuation, whitespace) over a hard character cut, but always falls
back to a hard cut at `max_chars` so a pathological input (no
boundaries at all) can't produce an unbounded chunk.
"""

from models import Document, DocumentChunk

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150

# Checked in this order (most-preferred boundary first) when looking
# backward from the hard cut point for a natural place to split.
_PARAGRAPH_BREAK = "\n\n"
_LINE_BREAK = "\n"
_SENTENCE_END_CHARS = "。！？.!?"
_WHITESPACE_CHARS = " 　\t"


def _find_cut_point(text: str, search_end: int, min_cut: int) -> int:
    """Looks backward from `search_end` (exclusive) for a natural
    boundary to cut at, no earlier than `min_cut`. Falls back to
    `search_end` itself (a hard cut) if no boundary is found in range.
    """
    idx = text.rfind(_PARAGRAPH_BREAK, min_cut, search_end)
    if idx != -1:
        return idx + len(_PARAGRAPH_BREAK)

    idx = text.rfind(_LINE_BREAK, min_cut, search_end)
    if idx != -1:
        return idx + len(_LINE_BREAK)

    for ch in _SENTENCE_END_CHARS:
        idx = text.rfind(ch, min_cut, search_end)
        if idx != -1:
            return idx + 1

    for ch in _WHITESPACE_CHARS:
        idx = text.rfind(ch, min_cut, search_end)
        if idx != -1:
            return idx + 1

    return search_end


def _split_text_into_ranges(
    text: str, max_chars: int, overlap_chars: int
) -> list[tuple[int, int]]:
    """Returns (start, end) character ranges covering `text`."""
    length = len(text)
    if length == 0:
        return []
    if length <= max_chars:
        return [(0, length)]

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < length:
        hard_end = min(start + max_chars, length)
        if hard_end == length:
            ranges.append((start, hard_end))
            break

        # Only look for a natural boundary in the back half of the
        # window, so a chunk never ends up suspiciously short just
        # because a boundary happened to sit early in the range.
        min_cut = start + max(1, max_chars // 2)
        end = _find_cut_point(text, hard_end, min_cut)
        if end <= start:
            end = hard_end

        ranges.append((start, end))

        next_start = end - overlap_chars
        # Guarantees forward progress even if overlap_chars is large
        # relative to the boundary found, avoiding an infinite loop.
        start = next_start if next_start > start else end

    return ranges


def chunk_document(
    document: Document,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[DocumentChunk]:
    """Splits a single Document's `text` into DocumentChunk[].

    `document.text` under `max_chars` becomes a single chunk. Longer
    text is split at natural boundaries where possible, each chunk
    overlapping the previous one by `overlap_chars` characters.
    Whitespace-only slices (e.g. right after a paragraph break) are
    dropped rather than becoming empty chunks. `charStart`/`charEnd`
    index into `document.text`, and `chunkIndex` starts at 0.
    """
    chunks: list[DocumentChunk] = []
    chunk_index = 0
    for start, end in _split_text_into_ranges(document.text, max_chars, overlap_chars):
        text = document.text[start:end]
        if not text.strip():
            continue

        chunks.append(
            DocumentChunk(
                id=f"{document.id}-chunk-{chunk_index}",
                documentId=document.id,
                sourceType=document.sourceType,
                sourceUrl=document.sourceUrl,
                title=document.title,
                domain=document.domain,
                chunkIndex=chunk_index,
                text=text,
                charStart=start,
                charEnd=end,
            )
        )
        chunk_index += 1

    return chunks


def chunk_documents(
    documents: list[Document],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[DocumentChunk]:
    """Chunks each Document in `documents`, concatenating the results."""
    chunks: list[DocumentChunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, max_chars=max_chars, overlap_chars=overlap_chars))
    return chunks
