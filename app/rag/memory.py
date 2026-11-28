import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

HISTORY_LIMIT = 6


def _connect():
    return psycopg.connect(
        dbname=os.getenv("DATABASE_NAME"),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT")),
    )


def _visitor(conn, visitor_id):
    """The id of an existing visitor, else of a new one. An unknown id is never
    inserted: like session ids, visitor ids are only ever created by the database."""
    if visitor_id is not None:
        row = conn.execute("SELECT id FROM visitors WHERE id = %s", (visitor_id,)).fetchone()
        if row:
            return row[0]
    return conn.execute("INSERT INTO visitors DEFAULT VALUES RETURNING id").fetchone()[0]


def open_conversation(session_id=None, visitor_id=None):
    """Return (conversation_id, session_id, visitor_id), in one transaction.

    - Known session_id: that conversation. Its visitor wins over the one sent: a
      conversation never moves to another visitor. A conversation without a visitor
      (from before visitors existed) is linked to the visitor sent, or a new one.
    - Missing or unknown session_id: a new conversation, linked to the visitor sent
      if it exists, else to a new visitor.
    Unknown ids are never reused: the database creates every id."""
    with _connect() as conn:
        if session_id is not None:
            row = conn.execute(
                "SELECT id, session_id, visitor_id FROM conversations WHERE session_id = %s "
                "FOR UPDATE",
                (session_id,),
            ).fetchone()
            if row:
                conversation_id, session_id, owner = row
                if owner is None:
                    owner = _visitor(conn, visitor_id)
                    conn.execute(
                        "UPDATE conversations SET visitor_id = %s WHERE id = %s",
                        (owner, conversation_id),
                    )
                return conversation_id, session_id, owner
        visitor_id = _visitor(conn, visitor_id)
        conversation_id, session_id = conn.execute(
            "INSERT INTO conversations (visitor_id) VALUES (%s) RETURNING id, session_id",
            (visitor_id,),
        ).fetchone()
        return conversation_id, session_id, visitor_id


def get_or_create_conversation(session_id=None):
    """Return (conversation_id, session_id); start a new conversation if needed
    (see open_conversation, which also returns the visitor)."""
    return open_conversation(session_id)[:2]


def save_message(conversation_id, role, content, reply_kind=None):
    """reply_kind is required for assistant messages and must be None for the others
    (enforced by the database)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, reply_kind) "
            "VALUES (%s, %s, %s, %s)",
            (conversation_id, role, content, reply_kind),
        )


def get_history(conversation_id, limit=HISTORY_LIMIT):
    # newest `limit` messages, returned oldest first
    with _connect() as conn:
        return conn.execute(
            "SELECT role, content FROM ("
            "  SELECT id, role, content FROM messages"
            "  WHERE conversation_id = %s ORDER BY id DESC LIMIT %s"
            ") AS last ORDER BY id",
            (conversation_id, limit),
        ).fetchall()
