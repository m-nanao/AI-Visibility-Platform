"""Tests for services/official_info_candidate.py's
build_official_info_candidate() (Task 6-D-5B,
feature/official-info-candidate).

Never calls a real network endpoint: fetch_url_texts()/to_documents()
are monkeypatched at this module's own namespace (both are imported by
name into services.official_info_candidate, so patching the name there
is what actually takes effect) — mirrors the established convention in
tests/test_main_chatgpt_websearch_supplement.py etc.
"""

import services.official_info_candidate as oic
from models import Document
from services.web_fetcher import UrlFetchResult


def _web_fetch_doc(url: str, *, title: str | None = None, text: str = "Official text.") -> Document:
    return Document(
        id=f"doc-{url}",
        sourceType="web_fetch",
        sourceUrl=url,
        title=title,
        domain=url,
        fetchedAt="2026-10-25T00:00:00Z",
        text=text,
    )


# --- officialUrl not provided: full backward compatibility ----------------


def test_returns_none_when_official_url_is_not_provided():
    assert oic.build_official_info_candidate(None, []) is None


def test_returns_none_when_official_url_is_blank_string():
    assert oic.build_official_info_candidate("", []) is None


def test_never_calls_fetch_when_official_url_is_not_provided(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_url_texts should not be called")

    monkeypatch.setattr(oic, "fetch_url_texts", fail_if_called)

    result = oic.build_official_info_candidate(None, [])

    assert result is None


# --- successful independent fetch ------------------------------------------


def test_successful_fetch_builds_a_success_candidate(monkeypatch):
    calls = []

    def fake_fetch_url_texts(urls):
        calls.append(urls)
        return [UrlFetchResult(url=urls[0], success=True, text="Official overview.", title="Acme Inc.")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    candidate = oic.build_official_info_candidate("https://acme.example.com", [])

    assert calls == [["https://acme.example.com"]]
    assert candidate is not None
    assert candidate.requestedUrl == "https://acme.example.com"
    assert candidate.status == "success"
    assert candidate.fetchedUrl == "https://acme.example.com"
    assert candidate.title == "Acme Inc."
    assert candidate.hasText is True
    assert candidate.fetchedAt is not None
    assert candidate.error is None
    # A freshly independent fetch never carries over another
    # Document's id — see the module's own docstring.
    assert candidate.documentId is None


def test_successful_fetch_with_no_text_sets_has_text_false(monkeypatch):
    def fake_fetch_url_texts(urls):
        return [UrlFetchResult(url=urls[0], success=True, text="", title=None)]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    candidate = oic.build_official_info_candidate("https://acme.example.com", [])

    # to_documents() only converts non-empty successful fetches in
    # practice, but defensively: empty text must never be reported as
    # hasText=True.
    assert candidate is not None
    assert candidate.status == "failed" or candidate.hasText is False


# --- fetch failure (SSRF rejection, timeout, non-200, etc.) -----------------


def test_fetch_failure_builds_a_failed_candidate_with_safe_error(monkeypatch):
    def fake_fetch_url_texts(urls):
        return [UrlFetchResult(url=urls[0], success=False, error="unsupported scheme: 'ftp'")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    candidate = oic.build_official_info_candidate("ftp://acme.example.com", [])

    assert candidate is not None
    assert candidate.status == "failed"
    assert candidate.error == "unsupported scheme: 'ftp'"
    assert candidate.fetchedUrl is None
    assert candidate.hasText is False
    assert candidate.title is None


def test_fetch_failure_never_fabricates_official_info(monkeypatch):
    """Task 6-D-5B item 2: 取得失敗時に公式情報を捏造しない."""

    def fake_fetch_url_texts(urls):
        return [UrlFetchResult(url=urls[0], success=False, error="timed out")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    candidate = oic.build_official_info_candidate("https://unreachable.example.com", [])

    assert candidate.status == "failed"
    assert candidate.title is None
    assert candidate.fetchedUrl is None


def test_ssrf_rejected_url_is_reported_as_a_failed_candidate_not_a_crash(monkeypatch):
    # Exercises the real _is_safe_url()/fetch_url_texts() path (no
    # monkeypatching of fetch_url_texts itself) against a private IP —
    # this must come back as success=False via the real SSRF check,
    # never raise.
    candidate = oic.build_official_info_candidate("http://127.0.0.1/admin", [])

    assert candidate is not None
    assert candidate.status == "failed"
    assert candidate.error is not None


# --- reuse of an already-fetched urls[] Document ---------------------------


def test_reuses_an_already_fetched_document_without_calling_fetch_again(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_url_texts should not be called when reuse is possible")

    monkeypatch.setattr(oic, "fetch_url_texts", fail_if_called)

    existing_doc = _web_fetch_doc("https://acme.example.com", title="Acme Inc.", text="Official text.")
    candidate = oic.build_official_info_candidate(
        "https://acme.example.com", [existing_doc]
    )

    assert candidate is not None
    assert candidate.status == "success"
    assert candidate.fetchedUrl == "https://acme.example.com"
    assert candidate.title == "Acme Inc."
    assert candidate.hasText is True
    # Reuse carries over the existing Document's own id — see the
    # module's own docstring for why this differs from a standalone
    # fetch.
    assert candidate.documentId == existing_doc.id


def test_reuse_requires_an_exact_string_match_not_a_normalized_one(monkeypatch):
    calls = []

    def fake_fetch_url_texts(urls):
        calls.append(urls)
        return [UrlFetchResult(url=urls[0], success=True, text="Official overview.", title="Acme")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    # Trailing slash differs from the existing Document's URL — this
    # must NOT be treated as a match (exact string comparison only,
    # per the module's own documented limitation).
    existing_doc = _web_fetch_doc("https://acme.example.com", title="Acme Inc.")
    candidate = oic.build_official_info_candidate(
        "https://acme.example.com/", [existing_doc]
    )

    assert len(calls) == 1  # a fresh fetch was issued, reuse did not apply.
    assert candidate.title == "Acme"  # from the fresh fetch, not the existing doc.


def test_reuse_only_considers_web_fetch_sourced_documents(monkeypatch):
    calls = []

    def fake_fetch_url_texts(urls):
        calls.append(urls)
        return [UrlFetchResult(url=urls[0], success=True, text="Official overview.", title="Acme")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    non_web_fetch_doc = Document(
        id="doc-common-crawl",
        sourceType="common_crawl",
        sourceUrl="https://acme.example.com",
        title="Stale Common Crawl copy",
        fetchedAt="2026-10-20T00:00:00Z",
        text="Old text.",
    )
    candidate = oic.build_official_info_candidate(
        "https://acme.example.com", [non_web_fetch_doc]
    )

    assert len(calls) == 1  # a fresh fetch was issued; the common_crawl doc was not reused.
    assert candidate.title == "Acme"


def test_reuse_matches_the_right_document_among_several():
    documents = [
        _web_fetch_doc("https://a.example.com", title="A"),
        _web_fetch_doc("https://acme.example.com", title="Acme Inc."),
        _web_fetch_doc("https://c.example.com", title="C"),
    ]
    candidate = oic.build_official_info_candidate("https://acme.example.com", documents)

    assert candidate.title == "Acme Inc."
    assert candidate.documentId == documents[1].id


# --- no unbounded text storage ----------------------------------------------


def test_candidate_never_exposes_the_document_text_itself(monkeypatch):
    """Task 6-D-5B item 3: 無制限のWeb本文保存を追加しない — the returned
    model has no field carrying the actual fetched text, only a
    boolean `hasText`."""

    def fake_fetch_url_texts(urls):
        return [UrlFetchResult(url=urls[0], success=True, text="A" * 50_000, title="Acme")]

    monkeypatch.setattr(oic, "fetch_url_texts", fake_fetch_url_texts)

    candidate = oic.build_official_info_candidate("https://acme.example.com", [])

    assert "text" not in candidate.model_dump()
    assert candidate.hasText is True
