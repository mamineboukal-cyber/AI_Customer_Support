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


@pytest.fixture(scope="session")
def test_db():
    """Name of a freshly migrated, empty database; dropped after the session."""
    assert TEST_DB != os.getenv("DATABASE_NAME"), "test DB must not be the real DB"
    _admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    _admin(f"CREATE DATABASE {TEST_DB}")

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
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    engine.dispose()

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
