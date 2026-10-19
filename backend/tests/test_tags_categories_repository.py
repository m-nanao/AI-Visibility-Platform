"""Verifies services.analysis_history_repository's tag/category CRUD
and attach/detach/set-category functions (feature/history-tags-
categories) without touching a real database — same monkeypatch
pattern as tests/test_analysis_history_repository.py (psycopg is
replaced at the module level with a bare fake object).

IMPORTANT: these tests exercise this module's *query-building and
exception-translation* logic. They cannot prove the real PostgreSQL
constraints (UNIQUE/CHECK/composite FK from migration 008) actually
behave as described — that is
tests/test_analysis_history_list_integration.py's job (real Postgres,
skipped without TEST_DATABASE_URL). Real psycopg.errors exception
*classes* are used here (imported directly from the installed psycopg
package) so that services.analysis_history_repository's pre-captured
UniqueViolation/ForeignKeyViolation/etc. module-level aliases (see
that module's comment on why it never writes `except
psycopg.errors.X:` directly) correctly match what the fake cursor
raises.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from services import analysis_history_repository as repo


class _FakeCursor:
    def __init__(self, *, fetchone_result=None, raise_on_execute=None):
        self.fetchone_result = fetchone_result
        self.raise_on_execute = raise_on_execute
        self.executed: list[tuple[str, object]] = []
        # Lets a test configure a *sequence* of fetchone() results —
        # needed for attach/detach/set-category, which look up the
        # run's status first (one query) before the actual write
        # (a second query).
        self._fetchone_queue: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute

    def fetchone(self):
        if self._fetchone_queue:
            return self._fetchone_queue.pop(0)
        return self.fetchone_result


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakePsycopg:
    def __init__(self, cursor):
        self._cursor = cursor
        self.connect_calls: list[tuple[str, int | None]] = []
        self.last_connection: _FakeConnection | None = None

    def connect(self, database_url, connect_timeout=None):
        self.connect_calls.append((database_url, connect_timeout))
        self.last_connection = _FakeConnection(self._cursor)
        return self.last_connection


def _configure_read_env(monkeypatch, *, url="postgresql://user:pass@host/db"):
    monkeypatch.setenv("DATABASE_URL", url)


VALID_ID = str(uuid.uuid4())
OTHER_ID = str(uuid.uuid4())


# --- create_tag -------------------------------------------------------


def test_create_tag_success(monkeypatch):
    _configure_read_env(monkeypatch)
    row = (VALID_ID, "project-1", "新規顧客")
    fake_cursor = _FakeCursor(fetchone_result=row)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    result = repo.create_tag(project_id="project-1", name="新規顧客")

    assert result == {"id": VALID_ID, "projectId": "project-1", "name": "新規顧客"}
    query, params = fake_cursor.executed[0]
    assert "insert into tags" in query.lower()
    assert params == ("project-1", "新規顧客")


def test_create_tag_raises_conflict_on_unique_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.UniqueViolation("dup"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.TagNameConflictError):
        repo.create_tag(project_id="project-1", name="新規顧客")


def test_create_tag_raises_invalid_on_check_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.CheckViolation("bad name"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.TagNameInvalidError):
        repo.create_tag(project_id="project-1", name="")


def test_create_tag_raises_read_error_on_other_failure(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=RuntimeError("boom"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.create_tag(project_id="project-1", name="新規顧客")


# --- list_tags ----------------------------------------------------------


def test_list_tags_no_filter(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor.fetchall = lambda: [(VALID_ID, "project-1", "A"), (OTHER_ID, "project-1", "B")]
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    result = repo.list_tags()

    assert result == [
        {"id": VALID_ID, "projectId": "project-1", "name": "A"},
        {"id": OTHER_ID, "projectId": "project-1", "name": "B"},
    ]
    query, _ = fake_cursor.executed[0]
    assert "order by name" in query.lower()


def test_list_tags_project_ids_empty_list_short_circuits(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakePsycopg(_FakeCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.list_tags(project_ids=[]) == []
    assert fake_psycopg.connect_calls == []


def test_list_tags_filters_by_project_ids_and_project_id(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor.fetchall = lambda: []
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    repo.list_tags(project_ids=["project-1", "project-2"], project_id="project-1")

    query, params = fake_cursor.executed[0]
    assert "project_id in (%s, %s)" in query.lower()
    assert "project_id = %s" in query.lower()
    assert params == ["project-1", "project-2", "project-1"]


# --- rename_tag -----------------------------------------------------------


def test_rename_tag_success(monkeypatch):
    _configure_read_env(monkeypatch)
    row = (VALID_ID, "project-1", "リネーム後")
    fake_cursor = _FakeCursor(fetchone_result=row)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    result = repo.rename_tag(VALID_ID, name="リネーム後")

    assert result == {"id": VALID_ID, "projectId": "project-1", "name": "リネーム後"}


def test_rename_tag_returns_none_for_malformed_id(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakePsycopg(_FakeCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.rename_tag("not-a-uuid", name="x") is None
    assert fake_psycopg.connect_calls == []


def test_rename_tag_returns_none_when_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.rename_tag(VALID_ID, name="x") is None


def test_rename_tag_raises_conflict_on_unique_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.UniqueViolation("dup"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.TagNameConflictError):
        repo.rename_tag(VALID_ID, name="dup")


# --- delete_tag -----------------------------------------------------------


def test_delete_tag_success(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=(VALID_ID,))
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.delete_tag(VALID_ID) is True
    assert fake_psycopg.last_connection.committed is True


def test_delete_tag_returns_false_when_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.delete_tag(VALID_ID) is False


def test_delete_tag_returns_false_for_malformed_id(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakePsycopg(_FakeCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.delete_tag("not-a-uuid") is False
    assert fake_psycopg.connect_calls == []


# --- create_category / list_categories / rename_category / delete_category
# (mirrors the tag tests above, one table swapped) ------------------------


def test_create_category_success(monkeypatch):
    _configure_read_env(monkeypatch)
    row = (VALID_ID, "project-1", "製品A")
    fake_cursor = _FakeCursor(fetchone_result=row)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    result = repo.create_category(project_id="project-1", name="製品A")

    assert result == {"id": VALID_ID, "projectId": "project-1", "name": "製品A"}


def test_create_category_raises_conflict_on_unique_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.UniqueViolation("dup"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.CategoryNameConflictError):
        repo.create_category(project_id="project-1", name="製品A")


def test_create_category_raises_invalid_on_check_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.CheckViolation("bad name"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.CategoryNameInvalidError):
        repo.create_category(project_id="project-1", name="")


def test_list_categories_project_ids_empty_list_short_circuits(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakePsycopg(_FakeCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.list_categories(project_ids=[]) == []
    assert fake_psycopg.connect_calls == []


def test_rename_category_success(monkeypatch):
    _configure_read_env(monkeypatch)
    row = (VALID_ID, "project-1", "製品B")
    fake_cursor = _FakeCursor(fetchone_result=row)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    result = repo.rename_category(VALID_ID, name="製品B")

    assert result == {"id": VALID_ID, "projectId": "project-1", "name": "製品B"}


def test_rename_category_raises_conflict_on_unique_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(raise_on_execute=psycopg.errors.UniqueViolation("dup"))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.CategoryNameConflictError):
        repo.rename_category(VALID_ID, name="dup")


def test_delete_category_success(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=(VALID_ID,))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.delete_category(VALID_ID) is True


def test_delete_category_returns_false_when_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.delete_category(VALID_ID) is False


# --- attach_tag_to_analysis_run -------------------------------------------


def test_attach_tag_success(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]  # status lookup
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.attach_tag_to_analysis_run(VALID_ID, OTHER_ID) is True
    assert fake_psycopg.last_connection.committed is True
    insert_query, insert_params = fake_cursor.executed[1]
    assert "insert into analysis_run_tags" in insert_query.lower()
    assert "on conflict" in insert_query.lower()
    assert insert_params == (OTHER_ID, VALID_ID)


def test_attach_tag_returns_false_when_run_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.attach_tag_to_analysis_run(VALID_ID, OTHER_ID) is False


def test_attach_tag_returns_false_for_malformed_run_id(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_psycopg = _FakePsycopg(_FakeCursor())
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.attach_tag_to_analysis_run("not-a-uuid", OTHER_ID) is False
    assert fake_psycopg.connect_calls == []


@pytest.mark.parametrize("status", ["queued", "running"])
def test_attach_tag_raises_status_conflict(monkeypatch, status):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=(status,))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisRunStatusConflictError) as exc_info:
        repo.attach_tag_to_analysis_run(VALID_ID, OTHER_ID)
    assert exc_info.value.status == status


def test_attach_tag_allowed_for_failed_status(monkeypatch):
    """'failed' is a terminal status but not in the blocking set —
    tag/category edits remain allowed, mirroring
    canManageHistoryListItem()'s frontend policy for failed jobs."""
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("failed",)]
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.attach_tag_to_analysis_run(VALID_ID, OTHER_ID) is True


def test_attach_tag_raises_not_assignable_on_foreign_key_violation(monkeypatch):
    """Simulates the tag belonging to a different project than the
    run — the composite FK on analysis_run_tags rejects the INSERT."""
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]

    call_count = {"n": 0}
    original_execute = fake_cursor.execute

    def execute_with_fk_violation_on_insert(query, params=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg.errors.ForeignKeyViolation("wrong project")
        return original_execute(query, params)

    fake_cursor.execute = execute_with_fk_violation_on_insert
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.TagNotAssignableError):
        repo.attach_tag_to_analysis_run(VALID_ID, OTHER_ID)


def test_attach_tag_raises_not_assignable_on_malformed_tag_id(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]

    call_count = {"n": 0}
    original_execute = fake_cursor.execute

    def execute_with_invalid_text_on_insert(query, params=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg.errors.InvalidTextRepresentation("bad uuid")
        return original_execute(query, params)

    fake_cursor.execute = execute_with_invalid_text_on_insert
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.TagNotAssignableError):
        repo.attach_tag_to_analysis_run(VALID_ID, "not-a-real-tag")


# --- detach_tag_from_analysis_run ------------------------------------------


def test_detach_tag_success(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.detach_tag_from_analysis_run(VALID_ID, OTHER_ID) is True
    assert fake_psycopg.last_connection.committed is True
    delete_query, delete_params = fake_cursor.executed[1]
    assert "delete from analysis_run_tags" in delete_query.lower()
    assert delete_params == (VALID_ID, OTHER_ID)


def test_detach_tag_returns_false_when_run_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.detach_tag_from_analysis_run(VALID_ID, OTHER_ID) is False


@pytest.mark.parametrize("status", ["queued", "running"])
def test_detach_tag_raises_status_conflict(monkeypatch, status):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=(status,))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisRunStatusConflictError):
        repo.detach_tag_from_analysis_run(VALID_ID, OTHER_ID)


def test_detach_tag_malformed_tag_id_is_a_harmless_no_op(monkeypatch):
    """A malformed tag_id can never have been attached — detaching it
    is idempotent success, not an error, mirroring a well-formed but
    unattached tag_id."""
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]

    call_count = {"n": 0}
    original_execute = fake_cursor.execute

    def execute_with_invalid_text_on_delete(query, params=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg.errors.InvalidTextRepresentation("bad uuid")
        return original_execute(query, params)

    fake_cursor.execute = execute_with_invalid_text_on_delete
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.detach_tag_from_analysis_run(VALID_ID, "not-a-real-tag") is True
    assert fake_psycopg.last_connection.rolled_back is True


# --- set_analysis_run_category ---------------------------------------------


def test_set_analysis_run_category_success(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]
    fake_psycopg = _FakePsycopg(fake_cursor)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)

    assert repo.set_analysis_run_category(VALID_ID, OTHER_ID) is True
    assert fake_psycopg.last_connection.committed is True
    update_query, update_params = fake_cursor.executed[1]
    assert "update analysis_runs set category_id" in update_query.lower()
    assert update_params == (OTHER_ID, VALID_ID)


def test_set_analysis_run_category_clear_to_none(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.set_analysis_run_category(VALID_ID, None) is True
    _, update_params = fake_cursor.executed[1]
    assert update_params == (None, VALID_ID)


def test_set_analysis_run_category_returns_false_when_run_not_found(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=None)
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.set_analysis_run_category(VALID_ID, OTHER_ID) is False


@pytest.mark.parametrize("status", ["queued", "running"])
def test_set_analysis_run_category_raises_status_conflict(monkeypatch, status):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor(fetchone_result=(status,))
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.AnalysisRunStatusConflictError):
        repo.set_analysis_run_category(VALID_ID, OTHER_ID)


def test_set_analysis_run_category_raises_requires_project_on_check_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]

    call_count = {"n": 0}
    original_execute = fake_cursor.execute

    def execute_with_check_violation_on_update(query, params=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg.errors.CheckViolation("project_id is null")
        return original_execute(query, params)

    fake_cursor.execute = execute_with_check_violation_on_update
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.CategoryRequiresProjectError):
        repo.set_analysis_run_category(VALID_ID, OTHER_ID)


def test_set_analysis_run_category_raises_not_assignable_on_foreign_key_violation(monkeypatch):
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]

    call_count = {"n": 0}
    original_execute = fake_cursor.execute

    def execute_with_fk_violation_on_update(query, params=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise psycopg.errors.ForeignKeyViolation("wrong project")
        return original_execute(query, params)

    fake_cursor.execute = execute_with_fk_violation_on_update
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    with pytest.raises(repo.CategoryNotAssignableError):
        repo.set_analysis_run_category(VALID_ID, OTHER_ID)


def test_set_analysis_run_category_never_rejects_clearing_regardless_of_project(monkeypatch):
    """Clearing a category (categoryId=null) must never trigger
    CategoryRequiresProjectError — the CHECK constraint only fires for
    a non-null category_id."""
    _configure_read_env(monkeypatch)
    fake_cursor = _FakeCursor()
    fake_cursor._fetchone_queue = [("completed",)]
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(fake_cursor))

    assert repo.set_analysis_run_category(VALID_ID, None) is True
