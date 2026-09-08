"""Verifies services.analysis_history_repository.save_analysis_history()
/ list_analysis_runs() / get_analysis_run() without ever touching a
real database — the module's psycopg/Jsonb names are monkeypatched
directly (see the module docstring for why that's possible: psycopg is
imported at module level, guarded by try/except ImportError).
"""

import uuid
from datetime import datetime, timezone

import pytest

from services import analysis_history_repository as repo


class _FakeJsonb:
    """Stand-in for psycopg.types.json.Jsonb — just remembers the value
    it wrapped so tests can assert on it without a real driver."""

    def __init__(self, value):
        self.value = value


class _FakeCursor:
    def __init__(self, existing_brand_id=None):
        self.existing_brand_id = existing_brand_id
        self.queries = []
        self._last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))
        self._last_query = query

    def fetchone(self):
        q = self._last_query.strip().lower()
        if q.startswith("select id from brands"):
            return (self.existing_brand_id,) if self.existing_brand_id else None
        if "insert into brands" in q:
            return ("new-brand-id",)
        if "insert into analysis_runs" in q:
            return ("new-run-id",)
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class _FakePsycopg:
    def __init__(self, cursor):
        self._cursor = cursor
        self.connect_calls = []

    def connect(self, database_url, connect_timeout=None):
        self.connect_calls.append((database_url, connect_timeout))
        return _FakeConnection(self._cursor)


def _configure_env(monkeypatch, *, enabled="true", url="postgresql://user:pass@host/db"):
    if enabled is None:
        monkeypatch.delenv("DB_SAVE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("DB_SAVE_ENABLED", enabled)
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)


def _call_save(**overrides):
    kwargs = dict(
        brand_name="サイボウズ",
        canonical_domain=None,
        input_snapshot={"brandName": "サイボウズ"},
        source_summary={"web_fetch": 1},
        result_json={"brandName": "サイボウズ"},
        visibility_score=42,
        meta_json={"documentsSource": "web_fetch"},
        status="completed",
    )
    kwargs.update(overrides)
    return repo.save_analysis_history(**kwargs)


# --- skip cases (no connection ever attempted) --------------------------


def test_skips_when_db_save_env_unset(monkeypatch):
    _configure_env(monkeypatch, enabled=None, url=None)
    assert _call_save() is None


def test_skips_when_database_url_missing(monkeypatch):
    _configure_env(monkeypatch, enabled="true", url=None)
    assert _call_save() is None


def test_skips_when_save_enabled_false(monkeypatch):
    _configure_env(monkeypatch, enabled="false")
    assert _call_save() is None


def test_skips_when_driver_not_installed(monkeypatch):
    _configure_env(monkeypatch, enabled="true")
    monkeypatch.setattr(repo, "psycopg", None)
    assert _call_save() is None


# --- success cases --------------------------------------------------------


def test_success_creates_new_brand(monkeypatch):
    _configure_env(monkeypatch, enabled="true")
    fake_cursor = _FakeCursor(existing_brand_id=None)
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)

    result = _call_save()

    assert result is not None
    assert result.brand_id == "new-brand-id"
    assert result.analysis_run_id == "new-run-id"
    assert fake_psycopg.connect_calls == [("postgresql://user:pass@host/db", 5)]


def test_success_reuses_existing_brand(monkeypatch):
    _configure_env(monkeypatch, enabled="true")
    fake_cursor = _FakeCursor(existing_brand_id="existing-brand-id")
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)

    result = _call_save()

    assert result is not None
    assert result.brand_id == "existing-brand-id"
    insert_brand_queries = [q for q, _ in fake_cursor.queries if "insert into brands" in q.lower()]
    assert insert_brand_queries == []


def test_none_source_summary_and_meta_are_passed_through_as_none(monkeypatch):
    _configure_env(monkeypatch, enabled="true")
    fake_cursor = _FakeCursor(existing_brand_id=None)
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)

    result = _call_save(source_summary=None, meta_json=None)

    assert result is not None
    _, run_params = next(
        (q, p) for q, p in fake_cursor.queries if "insert into analysis_runs" in q.lower()
    )
    # (brand_id, status, Jsonb(input_snapshot), source_summary) — the
    # 4th positional param must stay a plain None (real SQL NULL), not
    # a wrapped Jsonb(None).
    assert run_params[3] is None


# --- failure cases ---------------------------------------------------------


def test_connect_failure_returns_none_and_does_not_raise(monkeypatch):
    _configure_env(monkeypatch, enabled="true")

    class _RaisingPsycopg:
        def connect(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(repo, "psycopg", _RaisingPsycopg())
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)

    assert _call_save() is None


# --- list_analysis_runs() / get_analysis_run() ----------------------------
#
# Unlike save_analysis_history() above, these two never swallow
# failures — they raise AnalysisHistoryReadError instead (see the
# module docstring). Neither checks READ_HISTORY_ENABLED itself
# (that's main.py's job via services.db_settings.is_history_read_enabled());
# these tests only ever set DATABASE_URL.


class _FakeReadCursor:
    def __init__(self, *, fetchall_result=None, fetchone_result=None, raise_on_execute=None):
        self.fetchall_result = fetchall_result if fetchall_result is not None else []
        self.fetchone_result = fetchone_result
        self.raise_on_execute = raise_on_execute
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        self.executed.append((query, params))

    def fetchall(self):
        return self.fetchall_result

    def fetchone(self):
        return self.fetchone_result


class _FakeReadConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class _FakeReadPsycopg:
    def __init__(self, cursor):
        self._cursor = cursor
        self.connect_calls = []

    def connect(self, database_url, connect_timeout=None):
        self.connect_calls.append((database_url, connect_timeout))
        return _FakeReadConnection(self._cursor)


def _configure_read_env(monkeypatch, *, url="postgresql://user:pass@host/db"):
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)


VALID_RUN_ID = str(uuid.uuid4())
STARTED_AT = datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc)
COMPLETED_AT = datetime(2026, 9, 9, 0, 0, 10, tzinfo=timezone.utc)


# --- list_analysis_runs: skip/failure cases (no successful query) --------


def test_list_analysis_runs_raises_when_driver_not_installed(monkeypatch):
    _configure_read_env(monkeypatch)
    monkeypatch.setattr(repo, "psycopg", None)

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.list_analysis_runs()


def test_list_analysis_runs_raises_when_database_url_missing(monkeypatch):
    _configure_read_env(monkeypatch, url=None)
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(_FakeReadCursor()))

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.list_analysis_runs()


def test_list_analysis_runs_raises_on_query_failure(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(raise_on_execute=RuntimeError("connection refused"))
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.list_analysis_runs()


# --- list_analysis_runs: success cases ------------------------------------


def test_list_analysis_runs_success(monkeypatch):
    _configure_read_env(monkeypatch)
    row = (
        VALID_RUN_ID,
        "サイボウズ",
        "cybozu.co.jp",
        "completed",
        86,
        {"web_fetch": 1, "common_crawl": 3},
        STARTED_AT,
        COMPLETED_AT,
        COMPLETED_AT,
    )
    fake_cursor = _FakeReadCursor(fetchall_result=[row])
    fake_psycopg = _FakeReadPsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    items = repo.list_analysis_runs()

    assert items == [
        {
            "id": VALID_RUN_ID,
            "brandName": "サイボウズ",
            "canonicalDomain": "cybozu.co.jp",
            "status": "completed",
            "visibilityScore": 86,
            "sourceSummary": {"web_fetch": 1, "common_crawl": 3},
            "startedAt": STARTED_AT.isoformat(),
            "completedAt": COMPLETED_AT.isoformat(),
            "createdAt": COMPLETED_AT.isoformat(),
        }
    ]
    assert fake_psycopg.connect_calls == [("postgresql://user:pass@host/db", 5)]


def test_list_analysis_runs_clamps_limit_and_offset(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(fetchall_result=[])
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    repo.list_analysis_runs(limit=10_000, offset=-5)

    _, params = fake_cursor.executed[0]
    # limit/offset are always the last two positional params.
    assert params[-2] == repo.MAX_LIST_LIMIT
    assert params[-1] == 0


def test_list_analysis_runs_default_limit(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(fetchall_result=[])
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    repo.list_analysis_runs()

    _, params = fake_cursor.executed[0]
    assert params[-2] == repo.DEFAULT_LIST_LIMIT
    assert params[-1] == 0


def test_list_analysis_runs_applies_brand_and_status_filters(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(fetchall_result=[])
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    repo.list_analysis_runs(brand="サイボウズ", status="completed")

    query, params = fake_cursor.executed[0]
    assert "b.name = %s" in query
    assert "ar.status = %s" in query
    assert params[0] == "サイボウズ"
    assert params[1] == "completed"


def test_list_analysis_runs_no_filters_omits_where_clause(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(fetchall_result=[])
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    repo.list_analysis_runs()

    query, params = fake_cursor.executed[0]
    assert "where" not in query.lower()
    # Only limit/offset params when no filters are given.
    assert len(params) == 2


# --- get_analysis_run: invalid id / not found -----------------------------


def test_get_analysis_run_returns_none_for_invalid_uuid(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakeReadPsycopg(_FakeReadCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    result = repo.get_analysis_run("not-a-uuid")

    assert result is None
    # No DB connection should even be attempted for a malformed id.
    assert fake_psycopg.connect_calls == []


def test_get_analysis_run_returns_none_when_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    assert repo.get_analysis_run(VALID_RUN_ID) is None


# --- get_analysis_run: failure cases ---------------------------------------


def test_get_analysis_run_raises_when_driver_not_installed(monkeypatch):
    _configure_read_env(monkeypatch)
    monkeypatch.setattr(repo, "psycopg", None)

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.get_analysis_run(VALID_RUN_ID)


def test_get_analysis_run_raises_when_database_url_missing(monkeypatch):
    _configure_read_env(monkeypatch, url=None)
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(_FakeReadCursor()))

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.get_analysis_run(VALID_RUN_ID)


def test_get_analysis_run_raises_on_query_failure(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeReadCursor(raise_on_execute=RuntimeError("connection refused"))
    monkeypatch.setattr(repo, "psycopg", _FakeReadPsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.get_analysis_run(VALID_RUN_ID)


# --- get_analysis_run: success case ----------------------------------------


def test_get_analysis_run_success(monkeypatch):
    _configure_read_env(monkeypatch)
    brand_id = str(uuid.uuid4())
    row = (
        VALID_RUN_ID,
        brand_id,
        "サイボウズ",
        "cybozu.co.jp",
        "completed",
        {"brandName": "サイボウズ"},
        {"web_fetch": 1},
        STARTED_AT,
        COMPLETED_AT,
        {"brandName": "サイボウズ", "meta": {}},
        {"documentsSource": "web_fetch"},
    )
    fake_cursor = _FakeReadCursor(fetchone_result=row)
    fake_psycopg = _FakeReadPsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    result = repo.get_analysis_run(VALID_RUN_ID)

    assert result == {
        "id": VALID_RUN_ID,
        "brand": {
            "id": brand_id,
            "name": "サイボウズ",
            "canonicalDomain": "cybozu.co.jp",
        },
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "サイボウズ"},
            "sourceSummary": {"web_fetch": 1},
            "startedAt": STARTED_AT.isoformat(),
            "completedAt": COMPLETED_AT.isoformat(),
        },
        "result": {"brandName": "サイボウズ", "meta": {}},
        "meta": {"documentsSource": "web_fetch"},
    }
    assert fake_psycopg.connect_calls == [("postgresql://user:pass@host/db", 5)]
