"""Schema checks for the Alembic migrations. Needs the DB upgraded with `alembic upgrade head`."""
import os

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv()

TABLES = {
    "alembic_version",
    "conversations",
    "messages",
    "documents",
    "document_chunks",
    "unanswered_questions",
}


@pytest.fixture
def conn():
    # Plain connection, not get_conn(): register_vector() fails when the extension is missing,
    # and these tests must report that as an assertion, not crash.
    conn = psycopg.connect(
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT")),
    )
    yield conn
    conn.rollback()
    conn.close()


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
