"""Visitors and reply kinds through POST /chat, against the throwaway test DB.
No Gemini call: respond() is replaced; record_inquiry() runs for real."""
import uuid

import pytest
from fastapi.testclient import TestClient

import app.rag.answer as rag
from app.main import app
from app.rag.memory import open_conversation

client = TestClient(app)


@pytest.fixture
def reply_with(monkeypatch):
    """reply_with(AnswerResult) makes respond() return it."""
    def set_result(result):
        monkeypatch.setattr(rag, "respond", lambda question, history=None: result)

    set_result(rag.AnswerResult("Yes, 8 in stock."))
    return set_result


def post(message="Is the K1 in stock?", **ids):
    return client.post("/chat", json={"message": message, **{k: v for k, v in ids.items()}})


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def conversations(db):
    """[(session_id, visitor_id)] oldest first, as strings."""
    return [
        (str(s), v and str(v))
        for s, v in db.execute("SELECT session_id, visitor_id FROM conversations ORDER BY id")
    ]


def stored_kinds(db):
    return db.execute("SELECT role, reply_kind FROM messages ORDER BY id").fetchall()


# ---------------------------------------------------------------- visitors

def test_first_message_gets_a_server_created_visitor(memory_db, reply_with):
    body = post().json()

    visitor_id = str(uuid.UUID(body["visitor_id"]))
    assert conversations(memory_db) == [(body["session_id"], visitor_id)]
    assert count(memory_db, "visitors") == 1


def test_same_visitor_new_conversation_is_linked_to_the_same_visitor(memory_db, reply_with):
    first = post().json()

    # "New chat": no session_id, same visitor_id
    second = post("Hello again", visitor_id=first["visitor_id"]).json()

    assert second["visitor_id"] == first["visitor_id"]
    assert second["session_id"] != first["session_id"]
    assert conversations(memory_db) == [
        (first["session_id"], first["visitor_id"]),
        (second["session_id"], first["visitor_id"]),
    ]
    assert count(memory_db, "visitors") == 1


def test_continuing_a_conversation_keeps_its_visitor(memory_db, reply_with):
    first = post().json()

    again = post("and the X1?", session_id=first["session_id"], visitor_id=first["visitor_id"]).json()

    assert (again["session_id"], again["visitor_id"]) == (first["session_id"], first["visitor_id"])
    assert count(memory_db, "conversations") == 1
    assert count(memory_db, "messages") == 4


def test_unknown_visitor_id_gets_a_new_server_id(memory_db, reply_with):
    unknown = str(uuid.uuid4())

    body = post(visitor_id=unknown).json()

    assert body["visitor_id"] != unknown
    assert [str(r[0]) for r in memory_db.execute("SELECT id FROM visitors")] == [body["visitor_id"]]
    assert conversations(memory_db) == [(body["session_id"], body["visitor_id"])]


@pytest.mark.parametrize("visitor_id", ["string", "123", "", 42, "00000000-0000-0000-0000"])
def test_invalid_visitor_id_is_422_and_writes_nothing(memory_db, reply_with, visitor_id):
    response = post(visitor_id=visitor_id)

    assert response.status_code == 422
    for table in ("visitors", "conversations", "messages"):
        assert count(memory_db, table) == 0


def test_known_session_without_visitor_id_returns_the_conversations_visitor(memory_db, reply_with):
    first = post().json()

    # e.g. a page whose storage lost the visitor id but still has the session
    again = post("more", session_id=first["session_id"]).json()

    assert again["visitor_id"] == first["visitor_id"]
    assert count(memory_db, "visitors") == 1


def test_a_conversation_never_moves_to_another_visitor(memory_db, reply_with):
    a = post().json()
    b = post().json()

    again = post("more", session_id=a["session_id"], visitor_id=b["visitor_id"]).json()

    assert again["visitor_id"] == a["visitor_id"]
    assert conversations(memory_db) == [
        (a["session_id"], a["visitor_id"]),
        (b["session_id"], b["visitor_id"]),
    ]


def test_old_conversation_without_visitor_is_linked_to_the_visitor_sent(memory_db, reply_with):
    visitor = post().json()["visitor_id"]
    old_session = str(memory_db.execute(
        "INSERT INTO conversations DEFAULT VALUES RETURNING session_id"
    ).fetchone()[0])

    body = post("hi", session_id=old_session, visitor_id=visitor).json()

    assert (body["session_id"], body["visitor_id"]) == (old_session, visitor)
    assert (old_session, visitor) in conversations(memory_db)
    assert count(memory_db, "visitors") == 1


def test_old_conversation_without_visitor_gets_a_new_one_when_none_is_sent(memory_db):
    old_session = memory_db.execute(
        "INSERT INTO conversations DEFAULT VALUES RETURNING session_id"
    ).fetchone()[0]

    conversation_id, session_id, visitor_id = open_conversation(old_session)

    assert session_id == old_session and visitor_id is not None
    assert memory_db.execute(
        "SELECT visitor_id FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone() == (visitor_id,)


# ---------------------------------------------------------------- reply kinds

def flags(body):
    return body["reply_kind"], body["handoff"], body["inquiry"]


def test_normal_reply(memory_db, reply_with):
    body = post().json()

    assert body["reply"] == "Yes, 8 in stock."
    assert flags(body) == ("normal", False, False)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "normal")]


def test_handoff_reply(memory_db, reply_with):
    reply_with(rag.HANDOFF)

    body = post("i love you").json()

    assert body["reply"] == rag.HANDOFF_MESSAGE
    assert flags(body) == ("handoff", True, False)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "handoff")]


def test_error_reply_is_its_own_kind_and_not_a_handoff(memory_db, reply_with):
    reply_with(rag.AnswerResult(rag.ERROR_MESSAGE))

    body = post().json()

    assert body["reply"] == rag.ERROR_MESSAGE
    assert flags(body) == ("error", False, False)  # handoff stays as before: False
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "error")]


def test_recorded_inquiry(memory_db, reply_with):
    reply_with(rag.AnswerResult("We will check and come back to you.", "loyalty program"))

    body = post("Do you have a loyalty program?").json()

    assert body["reply"] == "We will check and come back to you."
    assert flags(body) == ("inquiry", False, True)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "inquiry")]
    assert count(memory_db, "admin_inquiries") == 1


def test_ignored_inquiry_becomes_a_handoff(memory_db, reply_with):
    memory_db.execute(
        "INSERT INTO unanswered_questions (question, normalized_question, status) "
        "VALUES ('loyalty program', 'loyalty program', 'ignored')"
    )
    reply_with(rag.AnswerResult("We will check and come back to you.", "loyalty program"))

    body = post("Do you have a loyalty program?").json()

    assert body["reply"] == rag.HANDOFF_MESSAGE
    assert flags(body) == ("handoff", True, False)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "handoff")]


def test_inquiry_that_cannot_be_recorded_is_an_error(memory_db, reply_with, monkeypatch):
    def broken(conversation_id, topic):
        raise RuntimeError("database down")

    monkeypatch.setattr(rag, "record_inquiry", broken)
    reply_with(rag.AnswerResult("We will check and come back to you.", "loyalty program"))

    body = post("Do you have a loyalty program?").json()

    assert body["reply"] == rag.ERROR_MESSAGE
    assert flags(body) == ("error", False, False)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "error")]


def test_chat_keeps_its_two_value_shape(memory_db, reply_with):
    reply, session_id = rag.chat("Is the K1 in stock?")

    assert reply == "Yes, 8 in stock."
    assert isinstance(session_id, uuid.UUID)
    assert stored_kinds(memory_db) == [("user", None), ("assistant", "normal")]
