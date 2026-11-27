"""The FastAPI app (app/main.py) against the throwaway test DB (conftest.py).
No Gemini call: respond() is replaced, so chat() still reads and saves the history."""
import uuid

import pytest
from fastapi.testclient import TestClient

import app.rag.answer as rag
from app.main import app

client = TestClient(app)


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@pytest.fixture
def fake_respond(monkeypatch):
    calls = []

    def respond(question, history=None):
        calls.append((question, list(history)))
        return rag.AnswerResult(f"reply to {question}", None)

    monkeypatch.setattr(rag, "respond", respond)
    return calls


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"message": "ok!"}


def test_chat_without_session_id_starts_a_conversation(memory_db, fake_respond):
    response = client.post("/chat", json={"message": "Is the K1 in stock?"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "reply to Is the K1 in stock?"
    assert body["handoff"] is False
    session_id = uuid.UUID(body["session_id"])
    assert memory_db.execute(
        "SELECT count(*) FROM conversations WHERE session_id = %s", (session_id,)
    ).fetchone()[0] == 1
    assert count(memory_db, "messages") == 2


def test_same_session_id_continues_the_conversation(memory_db, fake_respond):
    first = client.post("/chat", json={"message": "q1"}).json()

    second = client.post(
        "/chat", json={"message": "q2", "session_id": first["session_id"]}
    ).json()

    assert second["session_id"] == first["session_id"]
    assert fake_respond[-1] == ("q2", [("user", "q1"), ("assistant", "reply to q1")])
    assert count(memory_db, "conversations") == 1
    assert count(memory_db, "messages") == 4


def test_handoff_reply_is_flagged(memory_db, monkeypatch):
    monkeypatch.setattr(
        rag, "respond", lambda question, history=None: rag.AnswerResult(rag.HANDOFF_MESSAGE, None)
    )

    body = client.post("/chat", json={"message": "Can I speak to someone?"}).json()

    assert body["reply"] == rag.HANDOFF_MESSAGE
    assert body["handoff"] is True


@pytest.mark.parametrize("session_id", ["string", "123", "", 42])
def test_invalid_session_id_is_rejected_and_writes_nothing(memory_db, fake_respond, session_id):
    response = client.post("/chat", json={"message": "hi", "session_id": session_id})

    assert response.status_code == 422
    assert fake_respond == []
    assert count(memory_db, "conversations") == 0
    assert count(memory_db, "messages") == 0


def test_unknown_session_id_gets_a_new_server_id(memory_db, fake_respond):
    unknown = uuid.uuid4()

    body = client.post("/chat", json={"message": "hi", "session_id": str(unknown)}).json()

    new_id = uuid.UUID(body["session_id"])
    assert new_id != unknown
    assert fake_respond[-1] == ("hi", [])
    assert memory_db.execute(
        "SELECT session_id FROM conversations"
    ).fetchall() == [(new_id,)]


@pytest.mark.parametrize("message", ["", "x" * 2001])
def test_empty_or_too_long_message_is_rejected(memory_db, fake_respond, message):
    response = client.post("/chat", json={"message": message})

    assert response.status_code == 422
    assert fake_respond == []
    assert count(memory_db, "conversations") == 0


def test_message_of_2000_characters_is_accepted(memory_db, fake_respond):
    response = client.post("/chat", json={"message": "x" * 2000})

    assert response.status_code == 200
