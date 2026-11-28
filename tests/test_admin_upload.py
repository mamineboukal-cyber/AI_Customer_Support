"""POST /admin/upload against the throwaway test DB (conftest.py), with the inbox in
tmp_path. No Gemini call anywhere: the upload only loads, chunks and embeds."""
import asyncio
import io
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

import app.ingestion.ingest as ingest
import app.ingestion.upload as upload
from app.admin_api import MAX_REQUEST_BYTES
from app.ingestion.upload import MAX_UPLOAD_BYTES, UploadError, safe_pdf_name
from app.main import app

client = TestClient(app)

V1 = [["Wireless Headphones X1", "Price: 499 MAD", "Stock: 12"]]
V2 = [["Wireless Headphones X1", "Price: 459 MAD", "Stock: 3"]]


# ---------------------------------------------------------------- fixtures / helpers

@pytest.fixture
def inbox(tmp_path, monkeypatch, db, test_db):
    """Empty test DB, the app pointed at it, and an empty inbox under tmp_path/root."""
    monkeypatch.setenv("DATABASE_NAME", test_db)
    folder = tmp_path / "root" / "data" / "inbox"
    folder.mkdir(parents=True)
    monkeypatch.setattr(upload, "INBOX", folder)
    return folder


@pytest.fixture
def pdf(tmp_path, make_pdf):
    """pdf(pages) -> the bytes of a valid PDF with that text."""
    counter = iter(range(10_000))

    def build(pages):
        return make_pdf(tmp_path / f"src{next(counter)}.pdf", pages).read_bytes()

    return build


def post(name, data, content_type="application/pdf"):
    return client.post("/admin/upload", files={"file": (name, data, content_type)})


def files_under(folder: Path) -> list[str]:
    """Every file below folder (staging included), as relative posix paths."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def documents(conn):
    return conn.execute(
        "SELECT source_name, title, content FROM documents ORDER BY source_name"
    ).fetchall()


def chunk_ids(conn, source_name):
    return [r[0] for r in conn.execute(
        "SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.source_name = %s ORDER BY c.id",
        (source_name,),
    ).fetchall()]


def assert_nothing_written(inbox, db2):
    assert files_under(inbox) == []
    assert documents(db2) == []
    assert db2.execute("SELECT count(*) FROM document_chunks").fetchone()[0] == 0


# ---------------------------------------------------------------- success, replace, skip

def test_upload_creates_document_and_keeps_file_in_inbox(inbox, db2, pdf):
    data = pdf(V1)

    response = post("Headphones.pdf", data)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "Headphones.pdf"
    assert body["status"] == "created"
    assert body["chunks"] == len(chunk_ids(db2, "headphones")) > 0
    assert files_under(inbox) == ["Headphones.pdf"]  # no staging leftovers
    assert (inbox / "Headphones.pdf").read_bytes() == data
    [(source_name, title, content)] = documents(db2)
    assert (source_name, title) == ("headphones", "Headphones")
    assert "Price: 499 MAD" in content


def test_same_name_replaces_the_older_document(inbox, db2, pdf):
    post("headphones.pdf", pdf(V1))
    old_chunks = chunk_ids(db2, "headphones")
    new = pdf(V2)

    # Different case, same document (stem rule).
    response = post("Headphones.pdf", new)

    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    [(_, _, content)] = documents(db2)
    assert "Price: 459 MAD" in content and "499" not in content
    new_chunks = chunk_ids(db2, "headphones")
    assert response.json()["chunks"] == len(new_chunks)
    assert set(new_chunks).isdisjoint(old_chunks)
    assert (inbox / "Headphones.pdf").read_bytes() == new


def test_identical_upload_is_skipped(inbox, db2, pdf):
    data = pdf(V1)
    first = post("headphones.pdf", data).json()
    before = chunk_ids(db2, "headphones")

    response = post("headphones.pdf", data)

    assert response.status_code == 200
    assert response.json() == {"filename": "headphones.pdf", "status": "skipped", "chunks": first["chunks"]}
    assert chunk_ids(db2, "headphones") == before
    assert files_under(inbox) == ["headphones.pdf"]


# ---------------------------------------------------------------- limit 1: only PDF

@pytest.mark.parametrize("name", ["guide.txt", "guide.md", "guide", "guide.pdf.exe", "guide.pdf:x", "guide.pdf."])
def test_non_pdf_name_is_rejected(inbox, db2, pdf, name):
    response = post(name, pdf(V1))

    assert response.status_code == 415
    assert response.json() == {"detail": "only PDF files are accepted (the name must end in .pdf)"}
    assert_nothing_written(inbox, db2)


@pytest.mark.parametrize(
    "data",
    [b"", b"hello", b"PK\x03\x04 a zip", b" %PDF-1.4 leading space", b"%PDF"],
    ids=["empty", "text", "zip", "leading-space", "short"],
)
def test_content_must_start_with_pdf_magic(inbox, db2, data):
    response = post("guide.pdf", data)

    assert response.status_code == 415
    assert response.json() == {"detail": "not a PDF file: the content does not start with %PDF-"}
    assert_nothing_written(inbox, db2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": {"other": "x"}},
        {"data": {"file": "not a file"}},
        # A file part with an empty file name arrives as a text field.
        {"files": {"file": ("", b"%PDF-1.4 x", "application/pdf")}},
    ],
    ids=["no-field", "text-field", "empty-filename"],
)
def test_missing_file_is_a_clear_400(inbox, db2, kwargs):
    response = client.post("/admin/upload", **kwargs)

    assert response.status_code == 400
    assert response.json() == {"detail": "no file: send the PDF in a form field named 'file'"}
    assert_nothing_written(inbox, db2)


# ---------------------------------------------------------------- limit 2: 10 MB

def test_file_over_10_mb_is_413_and_not_kept(inbox, db2):
    data = b"%PDF-1.4\n" + b"0" * (MAX_UPLOAD_BYTES + 1 - 9)
    assert len(data) == MAX_UPLOAD_BYTES + 1

    response = post("big.pdf", data)

    assert response.status_code == 413
    assert response.json() == {"detail": "file too large: the limit is 10 MB"}
    assert_nothing_written(inbox, db2)


def test_copy_accepts_exactly_the_limit_and_refuses_one_byte_more(tmp_path):
    upload._copy_limited(io.BytesIO(b"x" * MAX_UPLOAD_BYTES), tmp_path / "ok.pdf")
    assert (tmp_path / "ok.pdf").stat().st_size == MAX_UPLOAD_BYTES

    with pytest.raises(UploadError) as e:
        upload._copy_limited(io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1)), tmp_path / "big.pdf")
    assert e.value.status == 413


def _raw_post(headers):
    """Call the ASGI app directly; receive() records whether the body was ever read."""
    reads = []

    async def receive():
        reads.append(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/admin/upload",
        "raw_path": b"/admin/upload", "root_path": "", "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "server": ("testserver", 80), "client": ("127.0.0.1", 50000),
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body), reads


def test_oversized_content_length_is_refused_before_reading_the_body(inbox):
    status, body, reads = _raw_post([
        ("content-type", "multipart/form-data; boundary=x"),
        ("content-length", str(MAX_REQUEST_BYTES + 1)),
    ])

    assert status == 413
    assert body == {"detail": "file too large: the limit is 10 MB"}
    assert reads == []  # not one byte of the body was received


def test_missing_content_length_is_411_without_reading_the_body(inbox):
    status, body, reads = _raw_post([("content-type", "multipart/form-data; boundary=x")])

    assert status == 411
    assert body == {"detail": "Content-Length header required"}
    assert reads == []


# ---------------------------------------------------------------- limit 3: file names

@pytest.mark.parametrize(
    "raw, safe",
    [
        ("guide.pdf", "guide.pdf"),
        ("Guide.PDF", "Guide.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\Windows\\win.ini.pdf", "win.ini.pdf"),
        ("C:\\Users\\admin\\Desktop\\Shipping FAQ.pdf", "Shipping FAQ.pdf"),
        ("/var/www/guide.pdf", "guide.pdf"),
        ("a..b.pdf", "a.b.pdf"),
        (".hidden.pdf", "hidden.pdf"),
        ("my <guide>|?*.pdf", "my _guide.pdf"),
        ("guide\x00.pdf", "guide.pdf"),
        ("prix:2026.pdf", "prix_2026.pdf"),
        ("trailing. .pdf", "trailing.pdf"),
        ("دليل الشحن.pdf", "دليل الشحن.pdf"),
        ("livraison-été.pdf", "livraison-été.pdf"),
        ("x" * 300 + ".pdf", "x" * 100 + ".pdf"),
    ],
)
def test_safe_pdf_name(raw, safe):
    assert safe_pdf_name(raw) == safe


@pytest.mark.parametrize(
    "raw, status",
    [
        (".pdf", 400), ("..pdf", 400), ("../.pdf", 400), ("<>|.pdf", 400), ("  .pdf", 400),
        ("con.pdf", 400), ("NUL.pdf", 400), ("com1.report.pdf", 400), ("LPT9.pdf", 400),
        (None, 415), ("", 415), ("guide", 415), ("guide.pdf.exe", 415), ("guide.pdf/", 415),
        ("guide.pdf\x00.txt", 415),
    ],
)
def test_unusable_names_are_rejected(raw, status):
    with pytest.raises(UploadError) as e:
        safe_pdf_name(raw)
    assert e.value.status == status


@pytest.mark.parametrize(
    "hostile", ["../../evil.pdf", "..\\..\\evil.pdf", "/tmp/evil.pdf", "C:\\evil.pdf", "../data/../evil.pdf"]
)
def test_path_traversal_name_stays_inside_the_inbox(inbox, db2, pdf, hostile):
    root = inbox.parents[1]  # tmp_path/root: inbox is root/data/inbox

    response = post(hostile, pdf(V1))

    assert response.status_code == 200
    assert response.json()["filename"] == "evil.pdf"
    assert files_under(root) == ["data/inbox/evil.pdf"]
    assert [d[0] for d in documents(db2)] == ["evil"]


# ---------------------------------------------------------------- limit 5: failed ingestion

def _encrypted(pdf_bytes):
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize(
    "kind, detail",
    [
        ("scan", "no extractable text in this PDF (a scan? run OCR first)"),
        ("encrypted", "PDF is encrypted: remove the password and try again"),
        ("corrupt", "cannot read PDF: "),
    ],
)
def test_unreadable_pdf_is_422_with_loader_message_and_leaves_nothing(inbox, db2, pdf, kind, detail):
    data = {
        "scan": lambda: pdf([[], []]),
        "encrypted": lambda: _encrypted(pdf(V1)),
        "corrupt": lambda: b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog",
    }[kind]()

    response = post("guide.pdf", data)

    assert response.status_code == 422
    assert response.json()["detail"].startswith(detail)
    assert_nothing_written(inbox, db2)


def test_error_during_ingestion_rolls_back_and_cleans_inbox(inbox, db2, pdf, monkeypatch):
    def broken_embedder(pieces):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(ingest, "embedder", broken_embedder)

    response = post("guide.pdf", pdf(V1))

    assert response.status_code == 500
    assert response.json() == {"detail": "ingestion failed: RuntimeError: model crashed"}
    assert_nothing_written(inbox, db2)  # the document row inserted before the crash is rolled back


def test_database_down_is_a_json_503_and_cleans_inbox(inbox, db2, pdf, monkeypatch):
    def no_database():
        raise OSError("connection refused")

    monkeypatch.setattr(upload, "connect", no_database)

    response = post("guide.pdf", pdf(V1))

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable: OSError: connection refused"}
    assert_nothing_written(inbox, db2)


def test_failed_replacement_keeps_the_previous_document_and_file(inbox, db2, pdf):
    good = pdf(V1)
    post("guide.pdf", good)
    before = documents(db2), chunk_ids(db2, "guide")

    response = post("guide.pdf", pdf([[]]))  # a scan with the same name

    assert response.status_code == 422
    assert (documents(db2), chunk_ids(db2, "guide")) == before
    assert files_under(inbox) == ["guide.pdf"]
    assert (inbox / "guide.pdf").read_bytes() == good


# ---------------------------------------------------------------- same name at the same time

def test_concurrent_uploads_of_one_name_are_serialised(inbox, db2, pdf):
    contents = [pdf(V1), pdf(V2)]
    barrier = threading.Barrier(2)
    results, errors = [], []

    def run(data):
        barrier.wait()
        try:
            results.append(upload.save_and_ingest(io.BytesIO(data), "guide.pdf"))
        except Exception as e:  # reported by the assert below
            errors.append(f"{type(e).__name__}: {getattr(e, 'detail', e)}")

    threads = [threading.Thread(target=run, args=(c,)) for c in contents]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(r.status for r in results) == ["created", "updated"]
    # The inbox file is the one whose text is in the database (the last one to commit).
    [(_, _, content)] = documents(db2)
    on_disk = (inbox / "guide.pdf").read_bytes()
    assert on_disk in contents
    assert ("459" in content) == (on_disk == contents[1])
    assert files_under(inbox) == ["guide.pdf"]
