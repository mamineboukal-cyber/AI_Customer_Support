"""Retrieval checks with no Gemini call. Needs the real DB migrated (alembic upgrade head)
and seeded (python -m app.ingestion.ingest_folder data/knowledge_base --keep)."""
import pytest

from app.embeddings.embedding import get_conn
from app.rag.search import search

PAYMENT = "cash on delivery\nor credit/debit card"

CASES = [
    ("How much is the Wireless Headphones X1?", "Price: 499 MAD"),
    ("How much is the Mechanical Keyboard K1?", "Price: 699 MAD"),
    ("Combien coûte la souris M1 ?", "Price: 249 MAD"),
    ("Is the Mechanical Keyboard K1 in stock?", "Stock: 8"),
    ("How many Wireless Mouse M1 do you have?", "Stock: 25"),
    ("How long is the warranty for the X1?", "Wireless Headphones X1:\n12-month warranty"),
    ("What is the warranty on the mouse M1?", "Warranty: 6 months"),
    ("Can I pay with cash on delivery?", PAYMENT),
    ("Which payment methods do you accept?", PAYMENT),
    ("Can I pay by card?", PAYMENT),
]


def test_knowledge_base_is_embedded():
    conn = get_conn()
    total, missing = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE embedding IS NULL) FROM document_chunks"
    ).fetchone()
    conn.close()
    assert total > 0, "document_chunks is empty: run python -m app.ingestion.ingest_folder data/knowledge_base --keep"
    assert missing == 0, f"{missing} chunks have no embedding: run app.embeddings.embedding"


@pytest.mark.parametrize("question,expected", CASES, ids=[q for q, _ in CASES])
def test_right_chunk_in_top3(question, expected):
    results = search(question)
    contents = [text for text, _ in results]
    assert any(expected in text for text in contents), (
        f"{expected!r} not in top 3:\n" + "\n---\n".join(contents)
    )
