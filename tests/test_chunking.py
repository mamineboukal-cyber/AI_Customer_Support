from pathlib import Path

import pytest

from app.ingestion.chunk_documents import CHUNK_OVERLAP, CHUNK_SIZE, split_text

KNOWLEDGE_BASE = Path(__file__).parents[1] / "data" / "knowledge_base"

SHIPPING = """
Shipping Policy

Delivery times depend on the destination city.
Casablanca: 1-2 business days.
Rabat: 1-2 business days.
Tangier: 2-3 business days.
Other cities: 2-5 business days.

Shipping is free for orders over 500 MAD.
Orders below this amount may incur a shipping fee.
"""


def test_chunk_settings():
    assert CHUNK_SIZE == 250
    assert CHUNK_OVERLAP == 40


def test_chunks_respect_size():
    chunks = split_text(SHIPPING)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


@pytest.mark.parametrize(
    "line",
    ["Casablanca: 1-2 business days.", "Shipping is free for orders over 500 MAD."],
)
def test_lines_not_cut(line):
    assert any(line in c for c in split_text(SHIPPING))


def test_short_text_single_chunk():
    assert split_text("Price: 499 MAD") == ["Price: 499 MAD"]


def test_empty_text():
    assert split_text("") == []


@pytest.mark.parametrize(
    "path", sorted(KNOWLEDGE_BASE.glob("*.md")), ids=lambda p: p.name
)
def test_knowledge_base_files_chunk_within_limit(path):
    chunks = split_text(path.read_text(encoding="utf-8"))
    assert chunks
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
