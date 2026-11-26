"""Record an admin inquiry: a conversation waits for an answer the documents do not have.

unanswered_questions is the ledger: one row per normalized question, `frequency` counts
the distinct conversations that asked it. admin_inquiries has one row per conversation
waiting on a ledger row.

Ledger rows that are no longer `pending` are never changed here:
- pending:  a new conversation adds 1 to frequency and gets a waiting inquiry.
- reviewed: the admin looked but there is no answer yet; the conversation still gets a
            waiting inquiry (the admin needs to know who is waiting).
- resolved: an approved answer exists; the conversation still gets a waiting inquiry,
            delivering the answer is the admin's job, not this module's.
- ignored:  the admin decided not to answer; no inquiry, and record_inquiry() returns
            False so the bot does not promise an answer that will never come.
"""
import re

from app.rag.memory import _connect

# Punctuation, symbols and "_" become spaces; letters and digits of any script stay.
_NOT_WORD = re.compile(r"[\W_]+")


def normalize_question(text):
    """Lowercase, punctuation to spaces, whitespace collapsed, trimmed."""
    return " ".join(_NOT_WORD.sub(" ", text.lower()).split())


def _ledger_row(conn, topic, normalized):
    """Return (id, status, created). A new row starts pending with frequency 1."""
    row = conn.execute(
        "INSERT INTO unanswered_questions (question, normalized_question) VALUES (%s, %s) "
        "ON CONFLICT (normalized_question) DO NOTHING RETURNING id, status",
        (topic, normalized),
    ).fetchone()
    if row:
        return row[0], row[1], True
    # Lock the row, so two conversations recording at once cannot lose a count.
    row = conn.execute(
        "SELECT id, status FROM unanswered_questions WHERE normalized_question = %s "
        "FOR UPDATE",
        (normalized,),
    ).fetchone()
    return row[0], row[1], False


def _insert_inquiry(conn, question_id, conversation_id):
    """True if a new waiting inquiry was created, False if this conversation already waits."""
    row = conn.execute(
        "INSERT INTO admin_inquiries (unanswered_question_id, conversation_id) "
        "VALUES (%s, %s) "
        "ON CONFLICT (unanswered_question_id, conversation_id) DO NOTHING RETURNING id",
        (question_id, conversation_id),
    ).fetchone()
    return row is not None


def record_inquiry(conversation_id, topic):
    """Record that `conversation_id` waits for an answer about `topic`, in one transaction.
    Returns False when the ledger row is `ignored` (nothing recorded), else True.
    Raises on any database error; nothing is written then."""
    normalized = normalize_question(topic)
    if not normalized:
        raise ValueError(f"empty inquiry topic: {topic!r}")
    with _connect() as conn:  # commits on success, rolls back on any exception
        question_id, status, created = _ledger_row(conn, topic.strip(), normalized)
        if status == "ignored":
            return False
        is_new = _insert_inquiry(conn, question_id, conversation_id)
        if is_new and not created and status == "pending":
            conn.execute(
                "UPDATE unanswered_questions SET frequency = frequency + 1 WHERE id = %s",
                (question_id,),
            )
        return True
