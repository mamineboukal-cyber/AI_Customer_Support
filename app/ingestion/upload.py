"""Save ONE uploaded PDF in data/inbox, ingest it with ingest_file (same rules as the
folder ingestion: one transaction, name stem = document, same name replaces, same text
skips), then move it to data/processed like ingest_folder does.

The upload is first written to a private staging folder inside the inbox
(data/inbox/.staging/<random>/<name>): ingest_folder ignores hidden entries and does not
walk sub-folders, so a half-written or rejected file is never seen as an inbox file.
Only after the transaction has committed (created, updated or skipped) is it moved to
data/processed/<name>, replacing a processed file of the same name. On any failure
the staging folder is deleted and the database is untouched (rolled back).

Uploads of the same document are serialised with a Postgres advisory lock held from
before the ingestion until the file is in data/processed, so the second one waits and
then reports "updated" or "skipped", and the processed file always matches the database.
"""
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.ingestion.ingest import connect, ingest_file
from app.ingestion.loaders import EmptyDocument, UnreadablePdf

INBOX = Path(__file__).resolve().parents[2] / "data" / "inbox"
PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"
STAGING_DIR = ".staging"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB, the PDF itself
PDF_MAGIC = b"%PDF-"
STEM_MAX = 100
COPY_BLOCK = 64 * 1024

# Letters and digits of any script (Arabic and French names are fine), space, dot,
# hyphen, underscore. Anything else, including path separators, : and control
# characters, becomes "_".
_UNSAFE = re.compile(r"[^\w .-]")
# Names Windows maps to devices whatever the extension (con.pdf is the console).
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10)}


class UploadError(Exception):
    """A rejected or failed upload. status is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class UploadResult:
    filename: str
    status: str  # "created" | "updated" | "skipped"
    chunks: int


def safe_pdf_name(raw: str | None) -> str:
    """The client's file name reduced to a safe base name ending in .pdf.
    Raises UploadError(415) when it is not a .pdf name, 400 when nothing usable is left."""
    name = unicodedata.normalize("NFC", raw or "")
    # Base name only, for both separators: a Windows client may send C:\x\y.pdf.
    name = re.split(r"[\\/]", name)[-1]
    stem, dot, ext = name.rpartition(".")
    if not dot or ext.strip().lower() != "pdf":
        raise UploadError(415, "only PDF files are accepted (the name must end in .pdf)")

    stem = _UNSAFE.sub("_", stem)
    stem = re.sub(r"\.{2,}", ".", stem)  # no ".." anywhere
    stem = re.sub(r"_{2,}", "_", stem)
    # No hidden files, and no trailing dot or space (Windows drops them silently).
    stem = stem.strip(" ._")[:STEM_MAX].rstrip(" .")
    if not stem:
        raise UploadError(400, "the file name has no usable characters; rename the file")
    if stem.split(".")[0].strip().lower() in _WINDOWS_DEVICES:
        raise UploadError(400, f"{stem!r} is a reserved file name; rename the file")
    return f"{stem}.pdf"


def _inside(folder: Path, path: Path) -> bool:
    return path.resolve().parent == folder.resolve()


def _copy_limited(src: BinaryIO, dest: Path) -> None:
    """Copy at most MAX_UPLOAD_BYTES, block by block; too large raises UploadError(413)."""
    size = 0
    with open(dest, "xb") as out:
        while block := src.read(COPY_BLOCK):
            size += len(block)
            if size > MAX_UPLOAD_BYTES:
                raise UploadError(413, f"file too large: the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            out.write(block)


def _chunk_count(conn, source_name: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.source_name = %s",
        (source_name,),
    ).fetchone()[0]


def save_and_ingest(
    src: BinaryIO, raw_name: str | None, inbox: Path | None = None, processed: Path | None = None
) -> UploadResult:
    inbox = inbox or INBOX
    processed = processed or PROCESSED
    name = safe_pdf_name(raw_name)

    if src.read(len(PDF_MAGIC)) != PDF_MAGIC:
        raise UploadError(415, "not a PDF file: the content does not start with %PDF-")
    src.seek(0)

    final = processed / name
    staging = inbox / STAGING_DIR / uuid.uuid4().hex
    staged = staging / name

    staging.mkdir(parents=True)
    try:
        processed.mkdir(parents=True, exist_ok=True)
        # Belt and braces after safe_pdf_name. Checked once both folders exist: on
        # Windows, resolve() of a missing path can differ from the same path resolved
        # a moment later, after another upload has created .staging.
        if not (_inside(processed, final) and _inside(staging, staged)):
            raise UploadError(400, "invalid file name")
        _copy_limited(src, staged)
        try:
            conn = connect()
        except Exception as e:
            raise UploadError(503, f"database unavailable: {type(e).__name__}: {e}") from None
        try:
            source_name = staged.stem.lower()  # the identity ingest_file uses
            # Session-level lock, released by the unlock below or when the
            # connection closes, whatever happens.
            conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (source_name,))
            try:
                status = ingest_file(staged, conn)
            except (UnreadablePdf, EmptyDocument) as e:
                raise UploadError(422, str(e)) from None
            except Exception as e:
                raise UploadError(500, f"ingestion failed: {type(e).__name__}: {e}") from None
            try:
                # Same as ingest_folder: replaces a processed file of the same name.
                os.replace(staged, final)
            except OSError as e:
                raise UploadError(
                    500,
                    f"the document was ingested ({status}) but the file could not be saved "
                    f"in data/processed: {type(e).__name__}: {e}",
                ) from None
            chunks = _chunk_count(conn, source_name)
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (source_name,))
        finally:
            conn.close()
    finally:
        # Only this upload's folder: the shared .staging folder stays (another upload
        # may be creating its own folder in it right now).
        shutil.rmtree(staging, ignore_errors=True)

    return UploadResult(filename=name, status=status, chunks=chunks)
