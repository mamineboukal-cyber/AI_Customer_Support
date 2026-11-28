"""Admin answer path: an admin answers one ledger question (unanswered_questions) and
every conversation waiting on it (admin_inquiries, status 'waiting') gets a reply.

Per conversation the model writes the reply first, outside any transaction; then one
transaction stores the raw admin answer (answered_at) and, when the reply is usable,
saves it as an assistant message and marks the inquiry delivered (delivered_at).
The status guard `WHERE status = 'waiting'` means an inquiry is never answered or
sent twice, even by two runs at once.

When the reply cannot be sent (model error, unusable reply, or the admin answer does
not cover the question) the inquiry stays 'answered', nothing is saved in the
conversation, and the result says why. Nothing retries those: only 'waiting'
inquiries are picked up.

The ledger row goes to 'reviewed' (not 'resolved': that needs an approved answer, and
approved_answer stays empty until the weekly review). A row that is already 'resolved'
or 'ignored' is left as it is.

Sending the reply (WhatsApp) is not done here: answer_inquiry() returns the replies.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime

from google.genai import types

from app.rag.memory import HISTORY_LIMIT, _connect, get_history

REPLY_INSTRUCTION = """You write one message from MoroccoTech's customer support (an electronics store in Morocco) to a customer.
Earlier the customer asked something we could not answer, and we promised to come back. A store admin has now given the answer.

Write the reply:
- In the language the customer used in the conversation (English, French, Arabic or Darija, including Darija in Latin letters).
- Short and natural, continuing the conversation.
- Use ONLY the information in the admin answer. Do not add any price, number, delay, condition, policy or other fact that is not in the admin answer. Do not guess.
- If the admin answer does not answer what the customer asked, set covered to false and leave reply empty.
"""

REPLY_CONFIG = types.GenerateContentConfig(
    system_instruction=REPLY_INSTRUCTION,
    response_mime_type="application/json",
    response_schema=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "covered": types.Schema(type=types.Type.BOOLEAN),
            "reply": types.Schema(type=types.Type.STRING),
        },
        required=["covered", "reply"],
    ),
)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class AdminAnswerError(ValueError):
    """A bad request: nothing was written."""


@dataclass(frozen=True)
class WaitingInquiry:
    inquiry_id: int
    ledger_id: int
    topic: str
    frequency: int
    conversation_id: int
    created_at: datetime


@dataclass(frozen=True)
class Delivery:
    inquiry_id: int
    conversation_id: int
    status: str  # delivered | not_covered | failed | skipped
    reply: str | None = None
    error: str | None = None


def list_waiting():
    """Every waiting inquiry, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT i.id, q.id, q.question, q.frequency, i.conversation_id, i.created_at "
            "FROM admin_inquiries i JOIN unanswered_questions q "
            "  ON q.id = i.unanswered_question_id "
            "WHERE i.status = 'waiting' ORDER BY i.created_at, i.id"
        ).fetchall()
    return [WaitingInquiry(*row) for row in rows]


def compose_reply(history, topic, admin_answer):
    """The reply text, or None when the admin answer does not cover the question.
    Raises when the model fails or its reply is unusable."""
    from app.rag import answer as rag  # loads the search model: only when replying

    conversation = "\n".join(
        f"{'customer' if role == 'user' else 'support'}: {text}" for role, text in history
    )
    prompt = (
        f"Conversation so far:\n{conversation}\n\n"
        f"Topic the customer asked about: {topic}\n\n"
        f"Admin answer: {admin_answer}\n\n"
        "Write the reply to the customer."
    )
    response = rag._generate([rag._text_content("user", prompt)], REPLY_CONFIG)
    try:
        data = json.loads(response.text or "")
    except json.JSONDecodeError as e:
        raise ValueError(f"the model did not return JSON: {response.text!r}") from e
    if not data.get("covered"):
        return None
    reply = (data.get("reply") or "").strip()
    if not reply:
        raise ValueError("the model returned an empty reply")
    added = set(_NUMBER.findall(reply)) - set(_NUMBER.findall(admin_answer))
    if added:
        raise ValueError(f"the reply adds numbers not in the admin answer: {sorted(added)}: {reply!r}")
    return reply


def _store(inquiry_id, conversation_id, admin_answer, reply):
    """One transaction. Returns False if the inquiry is no longer waiting."""
    with _connect() as conn:
        if reply is None:
            row = conn.execute(
                "UPDATE admin_inquiries SET status = 'answered', admin_answer = %s, "
                "answered_at = now() WHERE id = %s AND status = 'waiting' RETURNING id",
                (admin_answer, inquiry_id),
            ).fetchone()
            return row is not None
        row = conn.execute(
            "UPDATE admin_inquiries SET status = 'delivered', admin_answer = %s, "
            "answered_at = now(), delivered_at = now() "
            "WHERE id = %s AND status = 'waiting' RETURNING id",
            (admin_answer, inquiry_id),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            # The admin's answer, delivered: an answer like any other (migration 0006).
            "INSERT INTO messages (conversation_id, role, content, reply_kind) "
            "VALUES (%s, 'assistant', %s, 'normal')",
            (conversation_id, reply),
        )
        return True


def _answer_one(inquiry_id, conversation_id, topic, admin_answer):
    try:
        history = get_history(conversation_id, HISTORY_LIMIT)
        try:
            reply = compose_reply(history, topic, admin_answer)
            status, error = "delivered", None
            if reply is None:
                status, error = "not_covered", "the admin answer does not cover the question"
        except Exception as e:
            reply, status, error = None, "failed", str(e)
        if not _store(inquiry_id, conversation_id, admin_answer, reply):
            return Delivery(inquiry_id, conversation_id, "skipped",
                            error="no longer waiting (handled by another run)")
        return Delivery(inquiry_id, conversation_id, status, reply, error)
    except Exception as e:  # a database error for this conversation only
        return Delivery(inquiry_id, conversation_id, "failed", error=str(e))


def answer_inquiry(ledger_id, admin_answer):
    """Answer ledger question `ledger_id` for every conversation waiting on it.
    Returns one Delivery per conversation. Raises AdminAnswerError, before writing
    anything, for an empty answer, an unknown id, or no waiting inquiries."""
    if not (admin_answer or "").strip():
        raise AdminAnswerError("the admin answer is empty")
    with _connect() as conn:
        row = conn.execute(
            "SELECT question FROM unanswered_questions WHERE id = %s FOR UPDATE", (ledger_id,)
        ).fetchone()
        if row is None:
            raise AdminAnswerError(f"ledger question {ledger_id} does not exist")
        topic = row[0]
        waiting = conn.execute(
            "SELECT id, conversation_id FROM admin_inquiries "
            "WHERE unanswered_question_id = %s AND status = 'waiting' ORDER BY id",
            (ledger_id,),
        ).fetchall()
        if not waiting:
            raise AdminAnswerError(f"no waiting inquiries for ledger question {ledger_id}")
        conn.execute(
            "UPDATE unanswered_questions SET status = 'reviewed', reviewed_at = now() "
            "WHERE id = %s AND status IN ('pending', 'reviewed')",
            (ledger_id,),
        )
    return [_answer_one(i, c, topic, admin_answer) for i, c in waiting]
