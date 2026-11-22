"""Turn a file into plain text, chosen by extension. PDF/.docx loaders get added to LOADERS later."""
from pathlib import Path


class UnsupportedFileType(ValueError):
    pass


class EmptyDocument(ValueError):
    pass


def _read_utf8(path: Path) -> str:
    # utf-8-sig drops a BOM (Notepad adds one); text mode turns \r\n into \n,
    # so re-saving a file with Windows line endings does not change its hash.
    return path.read_text(encoding="utf-8-sig")


LOADERS = {
    ".md": _read_utf8,
    ".txt": _read_utf8,
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
