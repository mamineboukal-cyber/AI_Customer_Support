from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from app.ingestion.loaders import (
    EmptyDocument,
    NotUtf8,
    UnreadablePdf,
    UnsupportedFileType,
    load_text,
)


@pytest.mark.parametrize("name", ["a.md", "b.txt", "C.TXT", "d.Md"])
def test_supported_extensions_load(tmp_path, name):
    path = tmp_path / name
    path.write_text("Price: 499 MAD\n", encoding="utf-8")
    assert load_text(path) == "Price: 499 MAD"


@pytest.mark.parametrize("name", ["b.docx", "noext"])
def test_unsupported_extension_raises(tmp_path, name):
    path = tmp_path / name
    path.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFileType):
        load_text(path)


@pytest.mark.parametrize("content", ["", "  \n\n\t "])
def test_empty_file_raises(tmp_path, content):
    path = tmp_path / "empty.md"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(EmptyDocument):
        load_text(path)


def test_non_ascii_round_trip(tmp_path):
    text = "شحال ثمن السماعات X1؟\nLivrez-vous à Marrakech ?"
    path = tmp_path / "multi.md"
    path.write_text(text, encoding="utf-8")
    assert load_text(path) == text


def test_crlf_and_bom_give_same_text_as_lf(tmp_path):
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    lf.write_bytes("line one\nline two\n".encode("utf-8"))
    crlf.write_bytes("\ufeffline one\r\nline two\r\n".encode("utf-8"))
    assert load_text(crlf) == load_text(lf) == "line one\nline two"


def test_windows_1252_file_raises_clear_message(tmp_path):
    path = tmp_path / "livraison.txt"
    path.write_bytes("Livraison à Casablanca : 1–2 jours".encode("cp1252"))
    with pytest.raises(NotUtf8, match=r"not valid UTF-8 \(byte 0xe0 at position 10\): save the file as UTF-8"):
        load_text(path)


def test_arabic_windows_1256_file_is_rejected_not_garbled(tmp_path):
    path = tmp_path / "darija.txt"
    path.write_bytes("شحال ثمن السماعات X1؟".encode("cp1256"))
    with pytest.raises(NotUtf8):
        load_text(path)


# PDF: the files are built in the test (make_pdf in conftest.py), nothing binary is committed.
@pytest.mark.parametrize("name", ["guide.pdf", "GUIDE.PDF"])
def test_pdf_pages_are_joined_with_a_blank_line(tmp_path, make_pdf, name):
    path = make_pdf(tmp_path / name, [["Wireless Headphones X1", "Price: 499 MAD"], ["Delivery: 1-2 days"]])

    assert load_text(path) == "Wireless Headphones X1\nPrice: 499 MAD\n\nDelivery: 1-2 days"


def test_pdf_page_without_text_is_left_out(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "guide.pdf", [["Page one"], [], ["Page three"]])

    assert load_text(path) == "Page one\n\nPage three"


def test_pdf_control_characters_are_removed(tmp_path, make_pdf):
    # ReportLab bullets come out of pypdf as \x7f; Postgres also rejects \x00.
    path = make_pdf(tmp_path / "guide.pdf", [["\x7f Cash on delivery", "\x01Card\tonline"]])

    assert load_text(path) == "Cash on delivery\nCard\tonline"


def test_pdf_without_text_raises_clear_message(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "scan.pdf", [[], []])

    with pytest.raises(EmptyDocument, match=r"no extractable text in this PDF \(a scan\? run OCR first\)"):
        load_text(path)


@pytest.mark.parametrize(
    "data",
    [b"", b"not a pdf at all", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog", b"%PDF-1.4\n%%EOF\n"],
    ids=["empty", "not-pdf", "truncated", "no-objects"],
)
def test_corrupt_pdf_raises_unreadable(tmp_path, data):
    path = tmp_path / "broken.pdf"
    path.write_bytes(data)

    with pytest.raises(UnreadablePdf, match=r"^cannot read PDF: "):
        load_text(path)


@pytest.mark.parametrize("user_password", ["secret", ""])
def test_encrypted_pdf_raises_unreadable(tmp_path, make_pdf, user_password):
    plain = make_pdf(tmp_path / "plain.pdf", [["Price: 499 MAD"]])
    writer = PdfWriter(clone_from=PdfReader(plain))
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
    buffer = BytesIO()
    writer.write(buffer)
    path = tmp_path / "locked.pdf"
    path.write_bytes(buffer.getvalue())

    with pytest.raises(UnreadablePdf, match=r"^PDF is encrypted: remove the password and try again$"):
        load_text(path)
