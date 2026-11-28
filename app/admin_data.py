"""Database reads and writes behind the admin dashboard routes (app/admin_api.py)."""
from datetime import datetime

from app.rag.memory import _connect

# "Today" on the dashboard is this calendar day, not the UTC day. Postgres converts
# with its own time-zone database, so Morocco's clock changes (Ramadan) are handled
# there; nothing here assumes a fixed offset.
DASHBOARD_TIME_ZONE = "Africa/Casablanca"

PG_INTEGER_MAX = 2**31 - 1  # documents.id is an integer


def stats(now: datetime | None = None) -> dict:
    """The numbers for the dashboard home page. `now` (timezone-aware) picks the day;
    None means the database's now(). The day is [local midnight, next local midnight),
    computed by Postgres, so a 23- or 25-hour day around a clock change is right too."""
    with _connect() as conn:
        row = conn.execute(
            """
            WITH local_day AS (
                SELECT date_trunc('day', coalesce(%(now)s::timestamptz, now()) AT TIME ZONE %(tz)s) AS d
            ), bounds AS (
                SELECT d::date AS day,
                       d AT TIME ZONE %(tz)s AS start,
                       (d + interval '1 day') AT TIME ZONE %(tz)s AS stop
                FROM local_day
            ), today AS (
                SELECT m.conversation_id, m.role, m.reply_kind
                FROM messages m, bounds b
                WHERE m.created_at >= b.start AND m.created_at < b.stop
            )
            SELECT
                (SELECT day FROM bounds),
                (SELECT count(*) FROM admin_inquiries WHERE status = 'waiting'),
                (SELECT count(DISTINCT conversation_id) FROM today),
                (SELECT count(*) FROM today WHERE role = 'assistant' AND reply_kind = 'handoff'),
                (SELECT count(*) FROM today WHERE role = 'assistant' AND reply_kind = 'inquiry'),
                (SELECT count(*) FROM documents)
            """,
            {"now": now, "tz": DASHBOARD_TIME_ZONE},
        ).fetchone()
    day, waiting, conversations, handoffs, inquiries, documents = row
    return {
        "day": day.isoformat(),
        "time_zone": DASHBOARD_TIME_ZONE,
        "waiting_inquiries": waiting,
        "conversations_today": conversations,
        "handoffs_today": handoffs,
        "inquiries_today": inquiries,
        "documents": documents,
    }


def list_documents() -> list[dict]:
    """Every document, most recently added or updated first, with its chunk count."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.source_name, d.title, d.category, count(c.id),
                   d.created_at, d.updated_at
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC, d.id DESC
            """
        ).fetchall()
    keys = ("id", "name", "title", "category", "chunks", "created_at", "updated_at")
    return [dict(zip(keys, row)) for row in rows]


def delete_document(document_id: int) -> bool:
    """Delete the document and its chunks in one transaction. False if there is no
    such document (nothing is written then)."""
    if not 0 < document_id <= PG_INTEGER_MAX:
        return False
    with _connect() as conn:  # one transaction: commits at the end, rolls back on error
        # Locks the row first: an ingestion of the same document waits for this
        # transaction (ingest_file also locks it with FOR UPDATE) and then sees no row.
        found = conn.execute(
            "SELECT id FROM documents WHERE id = %s FOR UPDATE", (document_id,)
        ).fetchone()
        if found is None:
            return False
        # The foreign key has no ON DELETE CASCADE: chunks go first.
        conn.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    return True
