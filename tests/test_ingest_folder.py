"""ingest_folder / CLI against the throwaway test DB, with scratch folders in tmp_path
(never data/inbox). db2 is a second connection: it only sees committed data."""
import pytest

import app.ingestion.ingest as ingest
import app.ingestion.ingest_folder as ingest_folder_module
from app.ingestion.ingest_folder import find_document_collisions, ingest_folder, main

V1 = "Wireless Headphones X1\nPrice: 499 MAD"
OTHER = "Mechanical Keyboard K1\nPrice: 699 MAD"


@pytest.fixture
def inbox(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    return folder


@pytest.fixture
def processed(tmp_path):
    return tmp_path / "processed"


def put(folder, name, text):
    (folder / name).write_text(text, encoding="utf-8")


def by_name(results):
    return {r.path.name: r for r in results}


def has_document(conn, source_name):
    row = conn.execute("SELECT 1 FROM documents WHERE source_name = %s", (source_name,))
    return row.fetchone() is not None


def case_sensitive_fs(tmp_path):
    (tmp_path / "probe").write_text("x")
    return not (tmp_path / "PROBE").exists()


def test_success_moves_file_after_commit(inbox, processed, db, db2):
    put(inbox, "x1.md", V1)

    results = ingest_folder(inbox, processed, db)

    assert [(r.path.name, r.status, r.moved, r.error) for r in results] == [
        ("x1.md", "created", True, None)
    ]
    assert not (inbox / "x1.md").exists()
    assert (processed / "x1.md").read_text(encoding="utf-8") == V1
    assert has_document(db2, "x1")


# Case 2 at folder level: a skipped file is done, so it is moved too
def test_skipped_file_is_moved(inbox, processed, db):
    put(inbox, "x1.md", V1)
    ingest_folder(inbox, processed, db)
    put(inbox, "x1.md", V1)

    [result] = ingest_folder(inbox, processed, db)

    assert (result.status, result.moved) == ("skipped", True)
    assert not (inbox / "x1.md").exists()


# Case 3 at folder level: the failing file rolls back and stays; the others go on
def test_failure_halfway_stays_in_inbox_and_others_continue(
    inbox, processed, db, db2, monkeypatch
):
    real_embedder = ingest.embedder

    def embedder_failing_on_broken(texts):
        if any("BROKEN" in t for t in texts):
            raise RuntimeError("embedding model crashed")
        return real_embedder(texts)

    monkeypatch.setattr(ingest, "embedder", embedder_failing_on_broken)
    put(inbox, "a_good.md", V1)
    put(inbox, "b_broken.md", "BROKEN document text")
    put(inbox, "c_good.md", OTHER)

    results = by_name(ingest_folder(inbox, processed, db))

    broken = results["b_broken.md"]
    assert (broken.status, broken.moved) == ("failed", False)
    assert "RuntimeError" in broken.error and "embedding model crashed" in broken.error
    assert (inbox / "b_broken.md").exists()
    assert not (processed / "b_broken.md").exists()
    assert not has_document(db2, "b_broken")
    assert db2.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
    for name in ("a_good.md", "c_good.md"):
        assert (results[name].status, results[name].moved) == ("created", True)
        assert has_document(db2, name.removesuffix(".md"))


# Case 4 at folder level (plus unsupported types)
def test_empty_and_unsupported_files_stay_with_reason(inbox, processed, db, db2):
    put(inbox, "empty.txt", "")
    put(inbox, "blank.md", "  \n\n")
    put(inbox, "manual.docx", "PK not really a docx")

    results = by_name(ingest_folder(inbox, processed, db))

    assert {n: r.status for n, r in results.items()} == {
        "empty.txt": "failed",
        "blank.md": "failed",
        "manual.docx": "failed",
    }
    assert "empty" in results["empty.txt"].error
    assert "empty" in results["blank.md"].error
    assert "unsupported" in results["manual.docx"].error
    assert sorted(p.name for p in inbox.iterdir()) == ["blank.md", "empty.txt", "manual.docx"]
    assert db2.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


def test_keep_does_not_move(inbox, db, db2):
    put(inbox, "x1.md", V1)

    [result] = ingest_folder(inbox, None, db)

    assert (result.status, result.moved) == ("created", False)
    assert (inbox / "x1.md").exists()
    assert has_document(db2, "x1")


def test_ignores_gitkeep_hidden_files_and_folders(inbox, processed, db):
    put(inbox, ".gitkeep", "")
    put(inbox, ".draft.md", V1)
    (inbox / "sub").mkdir()

    assert ingest_folder(inbox, processed, db) == []
    assert (inbox / ".gitkeep").exists()


def test_existing_processed_file_is_replaced(inbox, processed, db):
    processed.mkdir()
    put(processed, "x1.md", "old copy")
    put(inbox, "x1.md", V1)

    [result] = ingest_folder(inbox, processed, db)

    assert (result.status, result.moved, result.error) == ("created", True, None)
    assert (processed / "x1.md").read_text(encoding="utf-8") == V1


def test_move_failure_is_reported_after_commit(inbox, tmp_path, db, db2):
    blocker = tmp_path / "processed"
    blocker.write_text("a file where the processed folder should be")
    put(inbox, "x1.md", V1)

    [result] = ingest_folder(inbox, blocker, db)

    assert (result.status, result.moved) == ("created", False)
    assert result.error.startswith("ingested but not moved")
    assert (inbox / "x1.md").exists()
    assert has_document(db2, "x1")


# Case 5: names that differ only by case
def test_find_document_collisions():
    names = ["FAQ.md", "Shipping.md", "faq.md", "shipping.txt", "SHIPPING.md", "x1.md", "x1.v2.md"]

    assert find_document_collisions(names) == {
        "faq.md": "FAQ.md",
        "shipping.txt": "Shipping.md",
        "SHIPPING.md": "Shipping.md",
    }


def test_case_collision_in_same_batch_keeps_second_file(inbox, processed, db, db2, tmp_path):
    if not case_sensitive_fs(tmp_path):
        pytest.skip("filesystem is case-insensitive: Shipping.md and shipping.md cannot coexist")
    put(inbox, "Shipping.md", V1)
    put(inbox, "shipping.md", OTHER)

    results = by_name(ingest_folder(inbox, processed, db))

    assert results["Shipping.md"].status == "created"
    assert results["shipping.md"].status == "failed"
    assert "same document as Shipping.md" in results["shipping.md"].error
    assert (inbox / "shipping.md").exists()
    content = db2.execute("SELECT content FROM documents WHERE source_name = 'shipping'")
    assert content.fetchone()[0] == V1


# Command line
def test_main_exit_codes(inbox, processed, db):
    put(inbox, "x1.md", V1)
    assert main([str(inbox), "--processed", str(processed)], conn=db) == 0

    put(inbox, "empty.md", "")
    assert main([str(inbox), "--processed", str(processed)], conn=db) == 1


def test_main_refuses_to_move_seed_folder_without_keep(monkeypatch):
    def no_connect():
        raise AssertionError("must not connect")

    monkeypatch.setattr(ingest_folder_module, "connect", no_connect)

    assert main(["data/knowledge_base"]) == 2


def test_case_collision_branch_on_any_filesystem(tmp_path, processed, db, db2, monkeypatch):
    # Same check as above, but the two case-variant files live in different folders
    # and are handed over as one listing, so it also runs on Windows.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    put(tmp_path / "a", "Shipping.md", V1)
    put(tmp_path / "b", "shipping.md", OTHER)
    listing = [tmp_path / "a" / "Shipping.md", tmp_path / "b" / "shipping.md"]
    monkeypatch.setattr(ingest_folder_module, "_files", lambda folder: listing)

    results = by_name(ingest_folder(tmp_path, processed, db))

    assert results["Shipping.md"].status == "created"
    assert results["shipping.md"].status == "failed"
    assert "same document as Shipping.md" in results["shipping.md"].error
    assert (tmp_path / "b" / "shipping.md").exists()
    content = db2.execute("SELECT content FROM documents WHERE source_name = 'shipping'")
    assert content.fetchone()[0] == V1


def test_same_stem_different_extension_in_same_batch(inbox, processed, db, db2):
    put(inbox, "shipping.md", V1)
    put(inbox, "shipping.txt", OTHER)

    results = by_name(ingest_folder(inbox, processed, db))

    assert results["shipping.md"].status == "created"
    assert results["shipping.txt"].status == "failed"
    assert "same document as shipping.md in this batch" in results["shipping.txt"].error
    assert (inbox / "shipping.txt").exists()
    content = db2.execute("SELECT content FROM documents WHERE source_name = 'shipping'")
    assert content.fetchone()[0] == V1


def test_folder_derives_categories_unless_given(inbox, db, db2):
    put(inbox, "FAQ.md", V1)
    put(inbox, "payments.md", OTHER)

    ingest_folder(inbox, None, db)

    rows = db2.execute("SELECT source_name, category FROM documents ORDER BY 1").fetchall()
    assert rows == [("faq", "faq"), ("payments", "payment")]


def test_main_category_option_overrides(inbox, processed, db, db2):
    put(inbox, "FAQ.md", V1)

    assert main([str(inbox), "--keep", "--category", "promo"], conn=db) == 0

    assert db2.execute("SELECT category FROM documents").fetchone()[0] == "promo"


# PDF: same pipeline as .md/.txt; a bad PDF fails alone and writes nothing.
GUIDE_PAGES = [["Wireless Headphones X1", "Price: 499 MAD"], ["Free shipping above 500 MAD"]]
GUIDE_TEXT = "Wireless Headphones X1\nPrice: 499 MAD\n\nFree shipping above 500 MAD"


def test_pdf_is_ingested_chunked_and_moved(inbox, processed, db, db2, make_pdf):
    make_pdf(inbox / "Store_Guide.pdf", GUIDE_PAGES)

    [result] = ingest_folder(inbox, processed, db)

    assert (result.status, result.moved, result.error) == ("created", True, None)
    assert (processed / "Store_Guide.pdf").exists()
    row = db2.execute(
        "SELECT d.title, d.content, count(c.id) FROM documents d "
        "JOIN document_chunks c ON c.document_id = d.id "
        "WHERE d.source_name = 'store_guide' GROUP BY d.id"
    ).fetchone()
    assert row == ("Store_Guide", GUIDE_TEXT, len(ingest.split_text(GUIDE_TEXT)))


def test_unchanged_pdf_is_skipped(inbox, processed, db, make_pdf):
    make_pdf(inbox / "guide.pdf", GUIDE_PAGES)
    ingest_folder(inbox, processed, db)
    make_pdf(inbox / "guide.pdf", GUIDE_PAGES)

    [result] = ingest_folder(inbox, processed, db)

    assert (result.status, result.moved) == ("skipped", True)


def test_pdf_replaces_md_with_the_same_name(inbox, processed, db, db2, make_pdf):
    put(inbox, "guide.md", V1)
    ingest_folder(inbox, processed, db)
    make_pdf(inbox / "Guide.pdf", GUIDE_PAGES)

    [result] = ingest_folder(inbox, processed, db)

    assert result.status == "updated"
    assert db2.execute("SELECT source_name, content FROM documents").fetchall() == [("guide", GUIDE_TEXT)]


def test_bad_pdfs_fail_alone_and_write_nothing(inbox, processed, db, db2, make_pdf):
    make_pdf(inbox / "good.pdf", GUIDE_PAGES)
    make_pdf(inbox / "scan.pdf", [[], []])
    (inbox / "broken.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")
    put(inbox, "notes.md", OTHER)

    results = by_name(ingest_folder(inbox, processed, db))

    assert {n: r.status for n, r in results.items()} == {
        "broken.pdf": "failed",
        "good.pdf": "created",
        "notes.md": "created",
        "scan.pdf": "failed",
    }
    assert results["scan.pdf"].error == (
        "EmptyDocument: no extractable text in this PDF (a scan? run OCR first)"
    )
    assert results["broken.pdf"].error.startswith("UnreadablePdf: cannot read PDF: ")
    assert sorted(p.name for p in inbox.iterdir()) == ["broken.pdf", "scan.pdf"]
    assert sorted(r[0] for r in db2.execute("SELECT source_name FROM documents")) == ["good", "notes"]


def test_main_exit_code_is_1_when_a_pdf_fails(inbox, processed, db, make_pdf):
    make_pdf(inbox / "scan.pdf", [[]])

    assert main([str(inbox), "--processed", str(processed)], conn=db) == 1
