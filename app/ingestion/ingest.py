"""Ingest ONE file: add or update its document, rebuild only its chunks, in one transaction."""
import hashlib
from pathlib import Path
from typing import Literal

import psycopg

from app.embeddings.embedding import embedder, get_conn
from app.ingestion.chunk_documents import split_text
from app.ingestion.loaders import load_text

TITLE_MAX = 50  # documents.title is varchar(50)


def connect() -> psycopg.Connection:
    """Connection for ingestion. Autocommit on purpose: with it off, any earlier statement
    opens an implicit transaction and conn.transaction() becomes a savepoint that never
    commits; with it on, each `with conn.transaction()` is one real transaction."""
    conn = get_conn()
    conn.autocommit = True
    return conn


def ingest_file(
    path: Path, conn: psycopg.Connection, category: str = "general"
) -> Literal["created", "updated", "skipped"]:
    if not conn.autocommit:
        raise ValueError("ingest_file needs an autocommit connection (use connect())")
    # Read and validate before touching the database: an unsupported or empty
    # file never reaches it.
    text = load_text(path)
    source_name = path.name.lower()  # case-insensitive identity (CHECK in migration 0003)
    title = path.stem[:TITLE_MAX]
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    with conn.transaction():
        existing = conn.execute(
            "SELECT id, content_hash FROM documents WHERE source_name = %s FOR UPDATE",
            (source_name,),
        ).fetchone()
        if existing and existing[1] == content_hash:
            return "skipped"

        document_id = conn.execute(
            "INSERT INTO documents (title, category, content, source_name, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (source_name) DO UPDATE SET "
            "title = EXCLUDED.title, category = EXCLUDED.category, "
            "content = EXCLUDED.content, content_hash = EXCLUDED.content_hash "
            "RETURNING id",
            (title, category, text, source_name, content_hash),
        ).fetchone()[0]

        conn.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
        pieces = split_text(text)
        vectors = embedder(pieces)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO document_chunks (document_id, content, chunk_index, embedding) "
                "VALUES (%s, %s, %s, %s)",
                [(document_id, piece, i, vectors[i]) for i, piece in enumerate(pieces)],
            )

    return "updated" if existing else "created"
