"""Verifies services.analysis_history_repository.save_analysis_history()
without ever touching a real database — the module's psycopg/Jsonb
names are monkeypatched directly (see the module docstring for why
that's possible: psycopg is imported at module level, guarded by
try/except ImportError).
"""

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
