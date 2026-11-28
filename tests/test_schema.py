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
    "visitors",
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

    migrate(command.upgrade, "0005_admin_inquiries")
    assert _has_0005(db) == (True, True, True)
    assert _version(db) == ("0005_admin_inquiries",)

    migrate(command.downgrade, "0004_source_name_stem")
    assert _has_0005(db) == (False, False, False)
    assert {"conversations", "unanswered_questions"} <= _tables(db)
    assert _version(db) == ("0004_source_name_stem",)

    migrate(command.upgrade, "0005_admin_inquiries")
    assert _has_0005(db) == (True, True, True)
    assert _version(db) == ("0005_admin_inquiries",)


# --- 0006: visitors, conversations.visitor_id, messages.reply_kind ------------------

# The texts migration 0006 backfills from, frozen there on purpose: when the app's
# messages are reworded later, the migration (and so this test) must not change.
HANDOFF_0006 = "I don't know. Let me connect you to a human agent."
ERROR_0006 = "Sorry, we are having a technical problem. Let me connect you to a human agent."


def _message(conn, conversation_id, role, content, kind=None):
    return conn.execute(
        "INSERT INTO messages (conversation_id, role, content, reply_kind) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (conversation_id, role, content, kind),
    ).fetchone()[0]


def test_visitor_defaults(conn):
    visitor_id, created_at = conn.execute(
        "INSERT INTO visitors DEFAULT VALUES RETURNING id, created_at"
    ).fetchone()
    assert visitor_id is not None and created_at is not None


def test_conversation_visitor_is_optional_and_set_null_on_delete(conn):
    assert _column(conn, "conversations", "visitor_id") == ("uuid", "YES")
    assert "(visitor_id)" in _index_def(conn, "idx_conversations_visitor_id")
    visitor = conn.execute("INSERT INTO visitors DEFAULT VALUES RETURNING id").fetchone()[0]
    linked = conn.execute(
        "INSERT INTO conversations (visitor_id) VALUES (%s) RETURNING id", (visitor,)
    ).fetchone()[0]
    _conversation(conn)  # no visitor: allowed

    conn.execute("DELETE FROM visitors WHERE id = %s", (visitor,))

    assert conn.execute(
        "SELECT visitor_id FROM conversations WHERE id = %s", (linked,)
    ).fetchone() == (None,)


def test_conversation_visitor_must_exist(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO conversations (visitor_id) VALUES (gen_random_uuid())"
        )


@pytest.mark.parametrize("kind", ["normal", "inquiry", "handoff", "error"])
def test_assistant_message_accepts_each_reply_kind(conn, kind):
    _message(conn, _conversation(conn), "assistant", "x", kind)


@pytest.mark.parametrize(
    "role, kind, constraint",
    [
        ("assistant", None, "messages_reply_kind_role_check"),
        ("user", "normal", "messages_reply_kind_role_check"),
        ("system", "handoff", "messages_reply_kind_role_check"),
        ("assistant", "unknown", "messages_reply_kind_check"),
        ("assistant", "Normal", "messages_reply_kind_check"),
    ],
)
def test_reply_kind_rejects(conn, role, kind, constraint):
    conversation_id = _conversation(conn)
    with pytest.raises(psycopg.errors.CheckViolation) as e:
        _message(conn, conversation_id, role, "x", kind)
    assert e.value.diag.constraint_name == constraint


def _has_0006(conn):
    return (
        "visitors" in _tables(conn),
        _column(conn, "conversations", "visitor_id") is not None,
        _column(conn, "messages", "reply_kind") is not None,
    )


def test_0006_backfills_existing_rows_and_goes_down_and_up(db, migrate):
    db.execute(
        "TRUNCATE visitors, conversations, messages, admin_inquiries, unanswered_questions "
        "RESTART IDENTITY"
    )
    migrate(command.downgrade, "0005_admin_inquiries")
    assert _has_0006(db) == (False, False, False)
    # Rows as the app wrote them before 0006 (no reply_kind column yet).
    conversation_id = _conversation(db)
    for role, content in [
        ("user", "Is the K1 in stock?"),
        ("assistant", "Yes, 8 in stock."),
        ("user", "i love you"),
        ("assistant", HANDOFF_0006),
        ("user", "price?"),
        ("assistant", ERROR_0006),
        ("assistant", "We will check and come back to you."),
        ("system", HANDOFF_0006),
    ]:
        db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content),
        )

    migrate(command.upgrade, "0006_visitors_reply_kind")

    assert _has_0006(db) == (True, True, True)
    assert db.execute("SELECT role, reply_kind FROM messages ORDER BY id").fetchall() == [
        ("user", None),
        ("assistant", "normal"),
        ("user", None),
        ("assistant", "handoff"),
        ("user", None),
        ("assistant", "error"),
        ("assistant", "normal"),  # a past inquiry promise cannot be recognised
        ("system", None),
    ]
    assert db.execute("SELECT visitor_id FROM conversations").fetchall() == [(None,)]

    migrate(command.downgrade, "0005_admin_inquiries")
    assert _has_0006(db) == (False, False, False)
    assert _version(db) == ("0005_admin_inquiries",)
    assert db.execute("SELECT count(*) FROM messages").fetchone() == (8,)  # rows kept

    migrate(command.upgrade, "0006_visitors_reply_kind")
    assert _has_0006(db) == (True, True, True)
    assert _version(db) == ("0006_visitors_reply_kind",)
    db.execute("TRUNCATE visitors, conversations, messages RESTART IDENTITY CASCADE")
