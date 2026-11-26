"""Schema checks: run against the throwaway test DB that conftest.py builds from empty
with `alembic upgrade head`, so every run also proves the migrations work from scratch."""
from datetime import datetime, timezone

import psycopg
import pytest
from alembic import command
from psycopg import sql

TABLES = {
    "admin_inquiries",
    "alembic_version",
    "conversations",
    "messages",
    "documents",
    "document_chunks",
    "unanswered_questions",
}


@pytest.fixture
def conn(raw_conn):
    # Not get_conn(): register_vector() fails when the extension is missing, and these
    # tests must report that as an assertion, not crash. Everything is rolled back.
    return raw_conn


def _insert_document(conn, source_name, content_hash):
    conn.execute(
        "INSERT INTO documents (title, category, content, source_name, content_hash) "
        "VALUES ('t', 'c', 'x', %s, %s)",
        (source_name, content_hash),
    )


def test_vector_extension_installed(conn):
    row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
    assert row is not None


def test_embedding_column_is_vector_384(conn):
    row = conn.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = to_regclass('public.document_chunks') AND attname = 'embedding'"
    ).fetchone()
    assert row == ("vector(384)",)


def test_all_tables_exist(conn):
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    assert TABLES <= {r[0] for r in rows}


def test_documents_source_name_unique(conn):
    _insert_document(conn, "_test_dup.md", "a" * 64)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_document(conn, "_test_dup.md", "b" * 64)


def test_documents_content_hash_not_null(conn):
    with pytest.raises(psycopg.errors.NotNullViolation):
        _insert_document(conn, "_test_nohash.md", None)


def test_documents_source_name_must_be_lowercase(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_document(conn, "Mixed.md", "a" * 64)


def _rows_at_0003(conn, migrate, names):
    migrate(command.downgrade, "0003_source_name_lowercase")
    for name in names:
        _insert_document(conn, name, "a" * 64)


# db: autocommit (an open transaction would hold a lock on documents and block the
# migrate fixture's cleanup) and starts from empty tables (other tests leave rows).
def test_0004_strips_extension_from_existing_rows(db, migrate):
    _rows_at_0003(db, migrate, ["shipping.md", "price.list.v2.txt", "noext"])

    migrate(command.upgrade, "head")

    rows = db.execute("SELECT source_name FROM documents ORDER BY source_name").fetchall()
    assert [r[0] for r in rows] == ["noext", "price.list.v2", "shipping"]


def test_0004_refuses_rows_that_would_merge(db, migrate):
    _rows_at_0003(db, migrate, ["shipping.md", "shipping.txt"])

    with pytest.raises(Exception, match="shipping.md, shipping.txt"):
        migrate(command.upgrade, "head")


# --- 0005: admin_inquiries and conversations.phone_number ---------------------------

NOW = datetime.now(timezone.utc)


def _conversation(conn, phone=None):
    return conn.execute(
        "INSERT INTO conversations (phone_number) VALUES (%s) RETURNING id", (phone,)
    ).fetchone()[0]


def _ledger_row(conn, text):
    return conn.execute(
        "INSERT INTO unanswered_questions (question, normalized_question) "
        "VALUES (%s, %s) RETURNING id",
        (text, text),
    ).fetchone()[0]


def _inquiry(conn, question_id, conversation_id, **cols):
    cols = {"unanswered_question_id": question_id, "conversation_id": conversation_id, **cols}
    query = sql.SQL("INSERT INTO admin_inquiries ({}) VALUES ({}) RETURNING id").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)),
    )
    return conn.execute(query, list(cols.values())).fetchone()[0]


def _tables(conn):
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {r[0] for r in rows.fetchall()}


def _column(conn, table, column):
    return conn.execute(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()


def _index_def(conn, name):
    row = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
        (name,),
    ).fetchone()
    return row and row[0]


def _version(conn):
    return conn.execute("SELECT version_num FROM alembic_version").fetchone()


def test_admin_inquiry_defaults(conn):
    inquiry = _inquiry(conn, _ledger_row(conn, "q"), _conversation(conn))

    row = conn.execute(
        "SELECT status, admin_answer, answered_at, delivered_at, created_at IS NOT NULL "
        "FROM admin_inquiries WHERE id = %s",
        (inquiry,),
    ).fetchone()
    assert row == ("waiting", None, None, None, True)


@pytest.mark.parametrize(
    "cols, constraint",
    [
        # A full answer, so only the status check can fire.
        (
            {"status": "pending", "admin_answer": "x", "answered_at": NOW, "delivered_at": NOW},
            "admin_inquiries_status_check",
        ),
        ({"status": "answered", "answered_at": NOW}, "admin_inquiries_answered_check"),
        ({"status": "answered", "admin_answer": "x"}, "admin_inquiries_answered_check"),
        (
            {"status": "delivered", "answered_at": NOW, "delivered_at": NOW},
            "admin_inquiries_answered_check",
        ),
        (
            {"status": "delivered", "admin_answer": "x", "answered_at": NOW},
            "admin_inquiries_delivered_check",
        ),
    ],
    ids=[
        "invalid-status",
        "answered-without-admin-answer",
        "answered-without-answered-at",
        "delivered-without-admin-answer",
        "delivered-without-delivered-at",
    ],
)
def test_admin_inquiry_rejects(conn, cols, constraint):
    question, conversation = _ledger_row(conn, "q"), _conversation(conn)

    with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
        _inquiry(conn, question, conversation, **cols)
    assert excinfo.value.diag.constraint_name == constraint


def test_admin_inquiry_accepts_valid_answered_and_delivered(conn):
    question = _ledger_row(conn, "q")
    _inquiry(conn, question, _conversation(conn),
             status="answered", admin_answer="x", answered_at=NOW)
    _inquiry(conn, question, _conversation(conn),
             status="delivered", admin_answer="x", answered_at=NOW, delivered_at=NOW)


def test_admin_inquiry_duplicate_pair_rejected(conn):
    q1, q2 = _ledger_row(conn, "q1"), _ledger_row(conn, "q2")
    c1, c2 = _conversation(conn), _conversation(conn)
    _inquiry(conn, q1, c1)
    _inquiry(conn, q1, c2)  # same question, another conversation
    _inquiry(conn, q2, c1)  # same conversation, another question

    with pytest.raises(psycopg.errors.UniqueViolation) as excinfo:
        _inquiry(conn, q1, c1)
    assert excinfo.value.diag.constraint_name == "admin_inquiries_question_conversation_key"


def test_deleting_conversation_cascades_to_inquiries(conn):
    question = _ledger_row(conn, "q")
    gone, kept = _conversation(conn), _conversation(conn)
    _inquiry(conn, question, gone)
    kept_inquiry = _inquiry(conn, question, kept)

    conn.execute("DELETE FROM conversations WHERE id = %s", (gone,))

    rows = conn.execute(
        "SELECT id FROM admin_inquiries WHERE unanswered_question_id = %s", (question,)
    ).fetchall()
    assert rows == [(kept_inquiry,)]
    assert conn.execute(
        "SELECT 1 FROM unanswered_questions WHERE id = %s", (question,)
    ).fetchone() == (1,)


def test_deleting_ledger_row_with_inquiry_is_restricted(conn):
    question = _ledger_row(conn, "q")
    _inquiry(conn, question, _conversation(conn))

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as excinfo:
        conn.execute("DELETE FROM unanswered_questions WHERE id = %s", (question,))
    assert excinfo.value.diag.constraint_name == "admin_inquiries_unanswered_question_id_fkey"


def test_deleting_ledger_row_without_inquiries_works(conn):
    question = _ledger_row(conn, "q")

    cur = conn.execute("DELETE FROM unanswered_questions WHERE id = %s", (question,))
    assert cur.rowcount == 1


def test_conversations_phone_number(conn):
    assert _column(conn, "conversations", "phone_number") == ("text", "YES")
    index = _index_def(conn, "idx_conversations_phone_number")
    assert index is not None and "UNIQUE" not in index
    # The same customer can have several conversations.
    _conversation(conn, "+212600000000")
    _conversation(conn, "+212600000000")


def test_admin_inquiries_indexes(conn):
    assert "(status)" in _index_def(conn, "idx_admin_inquiries_status")
    assert "(conversation_id)" in _index_def(conn, "idx_admin_inquiries_conversation_id")


def _has_0005(conn):
    return (
        "admin_inquiries" in _tables(conn),
        _column(conn, "conversations", "phone_number") is not None,
        _index_def(conn, "idx_conversations_phone_number") is not None,
    )


# db: autocommit, so no open transaction holds a lock while the migrations run DDL.
def test_0005_up_down_up_from_empty(db, migrate):
    migrate(command.downgrade, "base")
    assert _tables(db) == {"alembic_version"}

    migrate(command.upgrade, "head")
    assert _has_0005(db) == (True, True, True)
    assert _version(db) == ("0005_admin_inquiries",)

    migrate(command.downgrade, "0004_source_name_stem")
    assert _has_0005(db) == (False, False, False)
    assert {"conversations", "unanswered_questions"} <= _tables(db)
    assert _version(db) == ("0004_source_name_stem",)

    migrate(command.upgrade, "head")
    assert _has_0005(db) == (True, True, True)
    assert _version(db) == ("0005_admin_inquiries",)
