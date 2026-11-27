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


def get_or_create_conversation(session_id=None):
    """Return (conversation_id, session_id); start a new conversation if needed.
    An unknown session_id is not reused: the new conversation gets an id from the
    database, so a client can never choose its own session id."""
    with _connect() as conn:
        if session_id is not None:
            row = conn.execute(
                "SELECT id, session_id FROM conversations WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            if row:
                return row
        return conn.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id, session_id"
        ).fetchone()


def save_message(conversation_id, role, content):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content),
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
