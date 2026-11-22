import pytest

from app.ingestion.loaders import EmptyDocument, UnsupportedFileType, load_text


@pytest.mark.parametrize("name", ["a.md", "b.txt", "C.TXT", "d.Md"])
def test_supported_extensions_load(tmp_path, name):
    path = tmp_path / name
    path.write_text("Price: 499 MAD\n", encoding="utf-8")
    assert load_text(path) == "Price: 499 MAD"


@pytest.mark.parametrize("name", ["a.pdf", "b.docx", "noext"])
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
    crlf.write_bytes("﻿line one\r\nline two\r\n".encode("utf-8"))
    assert load_text(crlf) == load_text(lf) == "line one\nline two"
