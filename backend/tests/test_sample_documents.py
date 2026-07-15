from models import Document
from services.sample_documents import (
    SAMPLE_DOCUMENT_TEMPLATES,
    build_sample_documents,
    build_sample_documents_as_documents,
)


def test_build_sample_documents_as_documents_returns_one_document_per_template():
    documents = build_sample_documents_as_documents("OpenAI")

    assert len(documents) == len(SAMPLE_DOCUMENT_TEMPLATES)
    assert all(isinstance(document, Document) for document in documents)


def test_build_sample_documents_as_documents_sets_development_sample_source_type():
    documents = build_sample_documents_as_documents("OpenAI")

    assert all(document.sourceType == "development_sample" for document in documents)
    assert all(document.sourceUrl is None for document in documents)
    assert all(document.domain is None for document in documents)
    assert all(document.title == "開発用サンプル" for document in documents)


def test_build_sample_documents_as_documents_ids_are_unique_and_labeled():
    documents = build_sample_documents_as_documents("OpenAI")

    ids = [document.id for document in documents]
    assert len(set(ids)) == len(ids)
    assert all(document_id.startswith("development-sample-") for document_id in ids)


def test_build_sample_documents_as_documents_includes_purpose_metadata():
    documents = build_sample_documents_as_documents("OpenAI")

    assert all(document.metadata is not None for document in documents)
    assert all(
        document.metadata.get("purpose") == "development_sample" for document in documents
    )


def test_build_sample_documents_as_documents_normalizes_text(monkeypatch):
    import services.sample_documents as sample_documents_module

    calls = []

    def fake_normalize(text):
        calls.append(text)
        return "normalized"

    monkeypatch.setattr(sample_documents_module, "normalize_text", fake_normalize)

    documents = build_sample_documents_as_documents("OpenAI")

    assert len(calls) == len(SAMPLE_DOCUMENT_TEMPLATES)
    assert all(document.text == "normalized" for document in documents)


def test_build_sample_documents_as_documents_text_matches_raw_templates_for_plain_text():
    # Plain Japanese sample text has no full-width/invisible characters
    # to normalize, so normalize_text() should be a no-op here.
    raw_documents = build_sample_documents("Acme")
    documents = build_sample_documents_as_documents("Acme")

    assert [document.text for document in documents] == raw_documents
