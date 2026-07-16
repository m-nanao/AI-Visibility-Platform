from models import Document
from services.document_chunker import chunk_document, chunk_documents


def _make_document(text: str, **overrides) -> Document:
    defaults = dict(
        id="doc-1",
        sourceType="user_provided",
        fetchedAt="2026-07-17T00:00:00+00:00",
        text=text,
    )
    defaults.update(overrides)
    return Document(**defaults)


def test_short_document_becomes_a_single_chunk():
    document = _make_document("短い文章です。")

    chunks = chunk_document(document, max_chars=1200, overlap_chars=150)

    assert len(chunks) == 1
    assert chunks[0].text == document.text
    assert chunks[0].charStart == 0
    assert chunks[0].charEnd == len(document.text)


def test_long_document_becomes_multiple_chunks():
    document = _make_document("a" * 3000)

    chunks = chunk_document(document, max_chars=1000, overlap_chars=100)

    assert len(chunks) > 1


def test_chunk_index_starts_at_zero_and_is_sequential():
    document = _make_document("a" * 3000)

    chunks = chunk_document(document, max_chars=1000, overlap_chars=100)

    assert [c.chunkIndex for c in chunks] == list(range(len(chunks)))


def test_char_start_and_end_are_valid_and_cover_the_document():
    document = _make_document("a" * 3000)

    chunks = chunk_document(document, max_chars=1000, overlap_chars=100)

    for chunk in chunks:
        assert 0 <= chunk.charStart < chunk.charEnd <= len(document.text)
        assert chunk.text == document.text[chunk.charStart : chunk.charEnd]
    # The last chunk must reach the end of the document.
    assert chunks[-1].charEnd == len(document.text)


def test_overlap_chars_is_applied_between_consecutive_chunks():
    document = _make_document("a" * 3000)

    chunks = chunk_document(document, max_chars=1000, overlap_chars=100)

    for previous, current in zip(chunks, chunks[1:]):
        assert previous.charEnd - current.charStart == 100


def test_whitespace_only_slices_do_not_become_chunks():
    document = _make_document("文章1。\n\n   \n\n文章2。")

    chunks = chunk_document(document, max_chars=5, overlap_chars=1)

    assert all(chunk.text.strip() for chunk in chunks)
    assert [c.chunkIndex for c in chunks] == list(range(len(chunks)))


def test_empty_document_produces_no_chunks():
    assert chunk_document(_make_document("")) == []


def test_whitespace_only_document_produces_no_chunks():
    assert chunk_document(_make_document("   \n\t  ")) == []


def test_japanese_text_is_not_corrupted_and_prefers_sentence_boundaries():
    text = "これはテストの文章です。" * 100

    chunks = chunk_document(_make_document(text), max_chars=200, overlap_chars=20)

    assert len(chunks) > 1
    # Reassembling charStart/charEnd slices must reproduce valid
    # substrings of the original text (no corruption / off-by-one).
    for chunk in chunks:
        assert chunk.text == text[chunk.charStart : chunk.charEnd]
    # The first chunk should end right after a sentence-ending「。」,
    # confirming the natural-boundary search works for Japanese punctuation.
    assert text[chunks[0].charEnd - 1] == "。"


def test_chunks_inherit_source_metadata_from_document():
    document = _make_document(
        "a" * 3000,
        sourceType="web_fetch",
        sourceUrl="https://example.com/article",
        title="記事タイトル",
        domain="example.com",
    )

    chunks = chunk_document(document, max_chars=1000, overlap_chars=100)

    assert all(chunk.documentId == document.id for chunk in chunks)
    assert all(chunk.sourceType == "web_fetch" for chunk in chunks)
    assert all(chunk.sourceUrl == "https://example.com/article" for chunk in chunks)
    assert all(chunk.title == "記事タイトル" for chunk in chunks)
    assert all(chunk.domain == "example.com" for chunk in chunks)


def test_chunk_documents_processes_multiple_documents():
    documents = [
        _make_document("短い文章1です。", id="doc-a"),
        _make_document("短い文章2です。", id="doc-b"),
    ]

    chunks = chunk_documents(documents)

    assert len(chunks) == 2
    assert {chunk.documentId for chunk in chunks} == {"doc-a", "doc-b"}


def test_chunk_documents_handles_empty_list():
    assert chunk_documents([]) == []
