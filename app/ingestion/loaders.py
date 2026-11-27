"""Turn a file into plain text, chosen by extension. A .docx loader gets added to LOADERS later."""
import re
from pathlib import Path

from pypdf import PdfReader


class UnsupportedFileType(ValueError):
    pass


class EmptyDocument(ValueError):
    pass


class NotUtf8(ValueError):
    pass


class UnreadablePdf(ValueError):
    pass


# Control characters except tab and newline. pypdf returns some bullets as \x7f,
# and Postgres refuses \x00 in text, so none of them should reach the chunks.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _read_utf8(path: Path) -> str:
    # utf-8-sig drops a BOM (Notepad adds one); text mode turns \r\n into \n,
    # so re-saving a file with Windows line endings does not change its hash.
    # No fallback encoding on purpose: cp1252 decodes almost any bytes, so an Arabic
    # Windows-1256 file would be silently turned into garbage instead of rejected.
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise NotUtf8(
            f"not valid UTF-8 (byte {e.object[e.start]:#04x} at position {e.start}): "
            "save the file as UTF-8"
        ) from None


def _read_pdf(path: Path) -> str:
    # pypdf is a parser for files we did not write: any error it raises, while opening
    # or while reading a page, means "this file cannot be read", whatever its type.
    try:
        reader = PdfReader(path)
        encrypted = reader.is_encrypted
        # Refused even when it opens without a password (only an owner password):
        # an encrypted file is a sign it was not meant to be copied into the bot.
        if not encrypted:
            pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:
        raise UnreadablePdf(f"cannot read PDF: {type(e).__name__}: {e}") from None
    if encrypted:
        raise UnreadablePdf("PDF is encrypted: remove the password and try again")

    pages = [_CONTROL_CHARS.sub("", page).strip() for page in pages]
    text = "\n\n".join(page for page in pages if page)
    if not text:
        raise EmptyDocument("no extractable text in this PDF (a scan? run OCR first)")
    return text


LOADERS = {
    ".md": _read_utf8,
    ".txt": _read_utf8,
    ".pdf": _read_pdf,
}


def load_text(path: Path) -> str:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(LOADERS))
        raise UnsupportedFileType(f"unsupported file type {path.suffix or '(none)'!r}; supported: {supported}")
    text = loader(path).strip()
    if not text:
        raise EmptyDocument("file is empty")
    return text
