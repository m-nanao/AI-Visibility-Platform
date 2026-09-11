"""Verifies services/project_access.py's project/analysis-run access
checks without touching a real database. These functions take an
already-open connection rather than opening one themselves (unlike
services.analysis_history_repository's psycopg.connect()-based
functions), so every test just constructs a lightweight
FakeConnection/FakeCursor pair and passes it directly — no
monkeypatching of a `psycopg` module name is needed.
"""

import pytest

from services.project_access import (
    ProjectAccessError,
    can_user_access_analysis_run,
    can_user_access_project,
    get_accessible_project_ids,
)


class _FakeCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None, raise_error=False):
        self.fetchone_result = fetchone_result
        self.fetchall_result = fetchall_result if fetchall_result is not None else []
        self.raise_error = raise_error
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if self.raise_error:
            raise RuntimeError("boom")
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


# --- can_user_access_project -------------------------------------------


def test_can_user_access_project_true_when_member():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_project(conn, "user-1", "project-1") is True
    assert cursor.queries[0][1] == ("user-1", "project-1")
    assert "organization_members" in cursor.queries[0][0]
    assert "projects" in cursor.queries[0][0]


def test_can_user_access_project_false_when_not_member():
    cursor = _FakeCursor(fetchone_result=None)
    conn = _FakeConnection(cursor)

    assert can_user_access_project(conn, "user-1", "project-1") is False


def test_can_user_access_project_false_when_user_id_empty():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_project(conn, "", "project-1") is False
    assert cursor.queries == []


def test_can_user_access_project_false_when_project_id_empty():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_project(conn, "user-1", "") is False
    assert cursor.queries == []


def test_can_user_access_project_raises_on_db_error():
    cursor = _FakeCursor(raise_error=True)
    conn = _FakeConnection(cursor)

    with pytest.raises(ProjectAccessError):
        can_user_access_project(conn, "user-1", "project-1")


# --- can_user_access_analysis_run ---------------------------------------


def test_can_user_access_analysis_run_true_when_member_of_owning_project():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "user-1", "run-1") is True
    assert cursor.queries[0][1] == ("run-1", "user-1")
    assert "analysis_runs" in cursor.queries[0][0]
    assert "organization_members" in cursor.queries[0][0]


def test_can_user_access_analysis_run_false_when_not_member_of_owning_project():
    cursor = _FakeCursor(fetchone_result=None)
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "user-1", "run-1") is False


def test_can_user_access_analysis_run_false_when_run_does_not_exist():
    """A nonexistent analysis_run_id can never match the join, so the
    query returns no row — same fetchone()=None path as "not a
    member"."""
    cursor = _FakeCursor(fetchone_result=None)
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "user-1", "no-such-run") is False


def test_can_user_access_analysis_run_false_when_project_id_is_null():
    """analysis_runs.project_id IS NULL can never satisfy the inner
    join to projects.id, so it also surfaces as fetchone()=None —
    verified at the SQL-shape level (the query joins analysis_runs to
    projects via project_id, an inner join that excludes null)."""
    cursor = _FakeCursor(fetchone_result=None)
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "user-1", "run-without-project") is False
    query = cursor.queries[0][0]
    assert "join projects p on p.id = ar.project_id" in query


def test_can_user_access_analysis_run_false_when_user_id_empty():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "", "run-1") is False
    assert cursor.queries == []


def test_can_user_access_analysis_run_false_when_analysis_run_id_empty():
    cursor = _FakeCursor(fetchone_result=(1,))
    conn = _FakeConnection(cursor)

    assert can_user_access_analysis_run(conn, "user-1", "") is False
    assert cursor.queries == []


def test_can_user_access_analysis_run_raises_on_db_error():
    cursor = _FakeCursor(raise_error=True)
    conn = _FakeConnection(cursor)

    with pytest.raises(ProjectAccessError):
        can_user_access_analysis_run(conn, "user-1", "run-1")


# --- get_accessible_project_ids ------------------------------------------


def test_get_accessible_project_ids_returns_member_projects():
    cursor = _FakeCursor(fetchall_result=[("project-1",), ("project-2",)])
    conn = _FakeConnection(cursor)

    assert get_accessible_project_ids(conn, "user-1") == ["project-1", "project-2"]
    assert cursor.queries[0][1] == ("user-1",)


def test_get_accessible_project_ids_empty_when_no_membership():
    cursor = _FakeCursor(fetchall_result=[])
    conn = _FakeConnection(cursor)

    assert get_accessible_project_ids(conn, "user-1") == []


def test_get_accessible_project_ids_empty_when_user_id_empty():
    cursor = _FakeCursor(fetchall_result=[("project-1",)])
    conn = _FakeConnection(cursor)

    assert get_accessible_project_ids(conn, "") == []
    assert cursor.queries == []


def test_get_accessible_project_ids_deduplicates():
    cursor = _FakeCursor(
        fetchall_result=[("project-1",), ("project-1",), ("project-2",)]
    )
    conn = _FakeConnection(cursor)

    assert get_accessible_project_ids(conn, "user-1") == ["project-1", "project-2"]


def test_get_accessible_project_ids_raises_on_db_error():
    cursor = _FakeCursor(raise_error=True)
    conn = _FakeConnection(cursor)

    with pytest.raises(ProjectAccessError):
        get_accessible_project_ids(conn, "user-1")
