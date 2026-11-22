"""Ingest every file in a folder, one transaction per file.

    python -m app.ingestion.ingest_folder                       # data/inbox -> data/processed
    python -m app.ingestion.ingest_folder data/knowledge_base --keep   # seed, files stay

A file is moved to the processed folder only after its transaction has committed
(skipped files too: they are already in the database). A file that fails is rolled
back, left where it is, and reported; the other files and documents are untouched.
Exit code: 0 all good, 1 some file failed or could not be moved, 2 bad usage.
"""
import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.ingest import connect, ingest_file

KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"


@dataclass
class FileResult:
    path: Path
    status: str  # "created" | "updated" | "skipped" | "failed"
    moved: bool = False
    error: str | None = None


def find_document_collisions(names: list[str]) -> dict[str, str]:
    """Map each file name to the earlier one that is the same document
    (same name without extension, ignoring case: Shipping.md / shipping.txt)."""
    first_by_key = {}
    collisions = {}
    for name in names:
        key = Path(name).stem.lower()
        if key in first_by_key:
            collisions[name] = first_by_key[key]
        else:
            first_by_key[key] = name
    return collisions


def _files(folder: Path) -> list[Path]:
    # .gitkeep and other hidden files are not documents; sub-folders are not walked.
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def ingest_folder(
    folder: Path, processed: Path | None, conn, category: str | None = None
) -> list[FileResult]:
    """processed=None keeps every file in place (used for the seed folder)."""
    files = _files(folder)
    collisions = find_document_collisions([p.name for p in files])
    results = []

    for path in files:
        if path.name in collisions:
            results.append(
                FileResult(path, "failed", error=f"same document as {collisions[path.name]} in this batch")
            )
            continue
        try:
            status = ingest_file(path, conn, category)
        except Exception as e:  # report and go on with the next file
            results.append(FileResult(path, "failed", error=f"{type(e).__name__}: {e}"))
            continue

        result = FileResult(path, status)
        if processed is not None:
            # The transaction has committed at this point; a failed move is reported,
            # and the next run skips the unchanged file and retries the move.
            try:
                processed.mkdir(parents=True, exist_ok=True)
                os.replace(path, processed / path.name)
                result.moved = True
            except OSError as e:
                result.error = f"ingested but not moved: {type(e).__name__}: {e}"
        results.append(result)

    return results


def _print_report(results: list[FileResult], processed: Path | None) -> None:
    for r in results:
        line = f"{r.status:<8} {r.path.name}"
        if r.moved:
            line += f"  -> {processed}"
        if r.error:
            line += f"  ({r.error})"
        print(line)
    counts = Counter(r.status for r in results)
    summary = ", ".join(f"{counts[s]} {s}" for s in ("created", "updated", "skipped", "failed"))
    print(f"{len(results)} files: {summary}")


def main(argv=None, conn=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest every .md/.txt file in a folder.")
    parser.add_argument("folder", nargs="?", default="data/inbox", type=Path)
    parser.add_argument("--processed", default="data/processed", type=Path,
                        help="where ingested files are moved (default: data/processed)")
    parser.add_argument("--keep", action="store_true",
                        help="do not move files (for the tracked seed folder)")
    parser.add_argument("--category", default=None,
                        help="force this category (default: derived from each file name)")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"not a folder: {args.folder}", file=sys.stderr)
        return 2
    if not args.keep and args.folder.resolve() == KNOWLEDGE_BASE:
        print("data/knowledge_base is tracked seed data: use --keep", file=sys.stderr)
        return 2

    processed = None if args.keep else args.processed
    own_conn = conn is None
    if own_conn:
        conn = connect()
    try:
        results = ingest_folder(args.folder, processed, conn, args.category)
    finally:
        if own_conn:
            conn.close()

    _print_report(results, processed)
    return 1 if any(r.status == "failed" or r.error for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
