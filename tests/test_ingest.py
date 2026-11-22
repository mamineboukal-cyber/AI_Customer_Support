"""ingest_file against the throwaway test DB (conftest.py) with files in tmp_path.
Assertions read through db2, a second connection, so they only see committed data."""
import hashlib

import pytest

import app.ingestion.ingest as ingest
from app.ingestion.ingest import category_for, ingest_file
from app.ingestion.loaders import EmptyDocument

V1 = "Wireless Headphones X1\nPrice: 499 MAD\nStock: 12\nColors: black"
V2 = "Wireless Headphones X1\nPrice: 459 MAD\nStock: 3\nColors: black, white"
OTHER = "Mechanical Keyboard K1\nPrice: 699 MAD\nStock: 8"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(folder, name, text):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def document(conn, source_name):
    return conn.execute(
        "SELECT id, title, content, content_hash, updated_at, category FROM documents "
        "WHERE source_name = %s",
        (source_name,),
    ).fetchone()


def chunk_ids(conn, source_name):
    rows = conn.execute(
        "SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.source_name = %s ORDER BY c.id",
        (source_name,),
    ).fetchall()
    return [r[0] for r in rows]


def chunks(conn, source_name):
    return conn.execute(
        "SELECT c.content, c.embedding IS NOT NULL FROM document_chunks c "
        "JOIN documents d ON d.id = c.document_id WHERE d.source_name = %s ORDER BY c.chunk_index",
        (source_name,),
    ).fetchall()


def count_documents(conn):
    return conn.execute("SELECT count(*) FROM documents").fetchone()[0]


def test_new_file_is_created_and_committed(tmp_path, db, db2):
    path = write(tmp_path, "x1.md", V1)

    assert ingest_file(path, db) == "created"

    doc = document(db2, "x1")
    assert doc is not None
    assert doc[1] == "x1"
    assert doc[2] == V1
    assert doc[3] == sha(V1)
    rows = chunks(db2, "x1")
    assert rows and all(has_embedding for _, has_embedding in rows)
    assert "Price: 499 MAD" in "\n".join(text for text, _ in rows)


# Case 1: same file name, changed content
def test_changed_content_updates_only_that_document(tmp_path, db, db2):
    path = write(tmp_path, "x1.md", V1)
    ingest_file(path, db)
    ingest_file(write(tmp_path, "k1.md", OTHER), db)
    doc_id = document(db2, "x1")[0]
    old_ids = chunk_ids(db2, "x1")
    other_ids = chunk_ids(db2, "k1")

    write(tmp_path, "x1.md", V2)
    assert ingest_file(path, db) == "updated"

    doc = document(db2, "x1")
    assert doc[0] == doc_id
    assert doc[2] == V2
    assert doc[3] == sha(V2)
    new_ids = chunk_ids(db2, "x1")
    assert new_ids and not set(new_ids) & set(old_ids)
    text = "\n".join(t for t, _ in chunks(db2, "x1"))
    assert "Price: 459 MAD" in text and "Price: 499 MAD" not in text
    assert all(has_embedding for _, has_embedding in chunks(db2, "x1"))
    assert chunk_ids(db2, "k1") == other_ids
    assert count_documents(db2) == 2


# Case 2: same file name, identical content
def test_identical_content_is_skipped_without_writing(tmp_path, db, db2):
    path = write(tmp_path, "x1.md", V1)
    ingest_file(path, db)
    before = document(db2, "x1")
    ids = chunk_ids(db2, "x1")

    assert ingest_file(path, db) == "skipped"

    # set_updated_at fires on any UPDATE, so an unchanged updated_at proves no write
    assert document(db2, "x1") == before
    assert chunk_ids(db2, "x1") == ids


def test_crlf_resave_of_same_text_is_skipped(tmp_path, db):
    path = write(tmp_path, "x1.md", V1)
    ingest_file(path, db)
    path.write_bytes(V1.replace("\n", "\r\n").encode("utf-8"))

    assert ingest_file(path, db) == "skipped"


# Case 3: failure halfway (after the upsert and the chunk DELETE)
def _broken_embedder(_texts):
    raise RuntimeError("embedding model crashed")


def test_failure_on_new_file_leaves_nothing(tmp_path, db, db2, monkeypatch):
    monkeypatch.setattr(ingest, "embedder", _broken_embedder)
    path = write(tmp_path, "x1.md", V1)

    with pytest.raises(RuntimeError, match="embedding model crashed"):
        ingest_file(path, db)

    assert document(db2, "x1") is None
    assert db2.execute("SELECT count(*) FROM document_chunks").fetchone()[0] == 0


def test_failure_on_update_keeps_previous_version(tmp_path, db, db2, monkeypatch):
    path = write(tmp_path, "x1.md", V1)
    ingest_file(path, db)
    before = document(db2, "x1")
    ids = chunk_ids(db2, "x1")

    monkeypatch.setattr(ingest, "embedder", _broken_embedder)
    write(tmp_path, "x1.md", V2)
    with pytest.raises(RuntimeError):
        ingest_file(path, db)

    assert document(db2, "x1") == before
    assert chunk_ids(db2, "x1") == ids


def test_connection_usable_after_failure(tmp_path, db, monkeypatch):
    monkeypatch.setattr(ingest, "embedder", _broken_embedder)
    with pytest.raises(RuntimeError):
        ingest_file(write(tmp_path, "x1.md", V1), db)
    monkeypatch.undo()

    assert ingest_file(write(tmp_path, "k1.md", OTHER), db) == "created"


# Case 4: empty file
def test_empty_file_does_not_touch_existing_document(tmp_path, db, db2):
    path = write(tmp_path, "x1.md", V1)
    ingest_file(path, db)
    before = document(db2, "x1")
    ids = chunk_ids(db2, "x1")

    write(tmp_path, "x1.md", "   \n")
    with pytest.raises(EmptyDocument):
        ingest_file(path, db)

    assert document(db2, "x1") == before
    assert chunk_ids(db2, "x1") == ids


# Case 5: names that differ only by case are the same document
def test_case_variant_name_updates_same_document(tmp_path, db, db2):
    ingest_file(write(tmp_path / "first", "shipping.md", V1), db)
    doc_id = document(db2, "shipping")[0]

    status = ingest_file(write(tmp_path / "second", "Shipping.md", V2), db)

    assert status == "updated"
    assert count_documents(db2) == 1
    doc = document(db2, "shipping")
    assert doc[0] == doc_id
    assert doc[1] == "Shipping"
    assert doc[3] == sha(V2)


def test_case_variant_with_same_content_only_updates_title(tmp_path, db, db2):
    ingest_file(write(tmp_path / "first", "shipping.md", V1), db)
    ids = chunk_ids(db2, "shipping")

    assert ingest_file(write(tmp_path / "second", "SHIPPING.md", V1), db) == "updated"

    assert document(db2, "shipping")[1] == "SHIPPING"
    assert chunk_ids(db2, "shipping") == ids


def test_long_file_name_title_is_cut_to_50(tmp_path, db, db2):
    name = "a" * 80 + ".md"
    ingest_file(write(tmp_path, name, V1), db)

    assert document(db2, "a" * 80)[1] == "a" * 50


def test_refuses_non_autocommit_connection(tmp_path, raw_conn):
    # Without autocommit, conn.transaction() would only be a savepoint and never commit.
    with pytest.raises(ValueError, match="autocommit"):
        ingest_file(write(tmp_path, "x1.md", V1), raw_conn)


def test_other_extension_updates_same_document(tmp_path, db, db2):
    ingest_file(write(tmp_path, "shipping.md", V1), db)
    doc_id = document(db2, "shipping")[0]

    assert ingest_file(write(tmp_path, "shipping.txt", V2), db) == "updated"

    assert count_documents(db2) == 1
    assert document(db2, "shipping")[0] == doc_id
    assert document(db2, "shipping")[3] == sha(V2)


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("FAQ", "faq"),
        ("payments", "payment"),
        ("products", "products"),
        ("returns", "returns"),
        ("shipping", "shipping"),
        ("warranty", "warranty"),
        ("summer_delivery_update", "shipping"),
        ("Return-Policy", "returns"),
        ("x1_spec", "general"),
        ("returning_customers", "general"),
        ("productivity", "general"),
    ],
)
def test_category_for(stem, expected):
    assert category_for(stem) == expected


def test_new_document_gets_category_from_file_name(tmp_path, db, db2):
    ingest_file(write(tmp_path, "warranty.md", V1), db)

    assert document(db2, "warranty")[5] == "warranty"


def test_explicit_category_overrides(tmp_path, db, db2):
    ingest_file(write(tmp_path, "warranty.md", V1), db, category="promo")

    assert document(db2, "warranty")[5] == "promo"


def test_category_change_updates_row_without_rechunking(tmp_path, db, db2):
    path = write(tmp_path, "shipping.md", V1)
    ingest_file(path, db, category="general")
    before = document(db2, "shipping")
    ids = chunk_ids(db2, "shipping")

    assert ingest_file(path, db) == "updated"

    after = document(db2, "shipping")
    assert after[5] == "shipping"
    assert after[0] == before[0] and after[3] == before[3]
    assert after[4] > before[4]  # updated_at moved: the row was written
    assert chunk_ids(db2, "shipping") == ids  # nothing re-chunked or re-embedded
