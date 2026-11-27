"""Shared fixtures for tests that need a database.

They never use the real database: a throwaway database is created on the same
server for the test session, built with the Alembic migrations, and dropped at the end.
"""
import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sqlalchemy import URL, create_engine, pool

load_dotenv()

TEST_DB = "moroccotech_ingest_test"
ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def _params(dbname):
    return dict(
        dbname=dbname,
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT")),
    )


def _admin(sql):
    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    with psycopg.connect(**_params("postgres"), autocommit=True) as conn:
        conn.execute(sql)


def _run_alembic(fn, revision):
    """Run an Alembic command (command.upgrade / command.downgrade) on the test DB."""
    p = _params(TEST_DB)
    url = URL.create(
        "postgresql+psycopg",
        username=p["user"],
        password=p["password"],
        host=p["host"],
        port=p["port"],
        database=TEST_DB,
    )
    engine = create_engine(url, poolclass=pool.NullPool)
    cfg = Config(str(ALEMBIC_INI))
    try:
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            fn(cfg, revision)
    finally:
        engine.dispose()


@pytest.fixture
def migrate(test_db):
    """migrate(command.downgrade, "0003_...") etc. Afterwards the documents are removed
    (first: rows left at an old revision may block the upgrade) and the DB is back at head."""
    yield _run_alembic
    with psycopg.connect(**_params(test_db), autocommit=True) as conn:
        conn.execute("TRUNCATE documents, document_chunks")
    _run_alembic(command.upgrade, "head")


@pytest.fixture(scope="session")
def test_db():
    """Name of a freshly migrated, empty database; dropped after the session."""
    assert TEST_DB != os.getenv("DATABASE_NAME"), "test DB must not be the real DB"
    _admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    _admin(f"CREATE DATABASE {TEST_DB}")

    _run_alembic(command.upgrade, "head")

    yield TEST_DB
    _admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


def _connect(dbname):
    conn = psycopg.connect(**_params(dbname), autocommit=True)
    register_vector(conn)
    return conn


@pytest.fixture
def db(test_db):
    """Autocommit connection to the empty test DB (documents and chunks truncated)."""
    conn = _connect(test_db)
    conn.execute("TRUNCATE documents, document_chunks RESTART IDENTITY")
    yield conn
    conn.close()


@pytest.fixture
def raw_conn(test_db):
    """Plain transactional connection without register_vector(); rolled back at the end."""
    conn = psycopg.connect(**_params(test_db))
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def db2(test_db):
    """A second, independent connection: what it sees has really been committed."""
    conn = _connect(test_db)
    yield conn
    conn.close()

@pytest.fixture
def memory_db(db, test_db, monkeypatch):
    """The app connects through DATABASE_NAME: point it at the test DB, start empty.
    admin_inquiries must be truncated with conversations: it references them."""
    from app.rag import memory

    monkeypatch.setenv("DATABASE_NAME", test_db)
    with memory._connect() as conn:
        assert conn.info.dbname == test_db, "app tests must never touch the real DB"
    db.execute(
        "TRUNCATE conversations, messages, admin_inquiries, unanswered_questions "
        "RESTART IDENTITY"
    )
    return db


def _pdf_bytes(pages: list[list[str]]) -> bytes:
    """A minimal valid PDF, built by hand so no binary fixture is committed.
    Each page is a list of text lines (Helvetica); an empty list is a page with no
    text, like a scanned page without OCR."""
    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, lines in enumerate(pages):
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        shown = " T* ".join(f"({escape(line)}) Tj" for line in lines)
        stream = f"BT /F1 12 Tf 14 TL 72 720 Td {shown} ET".encode("latin-1")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = len(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


@pytest.fixture
def make_pdf():
    """make_pdf(path, [["page 1 line 1", "line 2"], ["page 2"]]) writes a PDF there."""
    def write(path: Path, pages: list[list[str]]) -> Path:
        path.write_bytes(_pdf_bytes(pages))
        return path

    return write
