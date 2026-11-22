"""Schema checks: run against the throwaway test DB that conftest.py builds from empty
with `alembic upgrade head`, so every run also proves the migrations work from scratch."""
import psycopg
import pytest
from alembic import command

TABLES = {
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
