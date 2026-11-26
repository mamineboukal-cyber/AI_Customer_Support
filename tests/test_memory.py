"""Conversation memory and chat() against the throwaway test DB (conftest.py).
No Gemini call: answer() is replaced, or _generate() is replaced so answer() runs
without the client."""
import uuid
from types import SimpleNamespace

import pytest

import app.rag.answer as rag
from app.rag import memory
from app.rag.memory import get_history, get_or_create_conversation, save_message


def messages(conn, conversation_id):
    return conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()


def save_turns(conversation_id, n):
    for i in range(1, n + 1):
        save_message(conversation_id, "user", f"q{i}")
        save_message(conversation_id, "assistant", f"r{i}")


# (1) get_or_create_conversation
def test_new_conversation_is_created_with_a_session_id(memory_db):
    conversation_id, session_id = get_or_create_conversation()

    assert isinstance(session_id, uuid.UUID)
    row = memory_db.execute(
        "SELECT session_id, status FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    assert row == (session_id, "active")


def test_same_session_id_returns_same_conversation(memory_db):
    first = get_or_create_conversation()

    assert get_or_create_conversation(first[1]) == first
    assert memory_db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1


def test_unknown_session_id_creates_conversation_with_that_id(memory_db):
    wanted = uuid.uuid4()

    conversation_id, session_id = get_or_create_conversation(wanted)

    assert session_id == wanted
    assert get_or_create_conversation(wanted) == (conversation_id, wanted)


def test_no_session_id_always_starts_a_new_conversation(memory_db):
    assert get_or_create_conversation() != get_or_create_conversation()


# (2) save_message / get_history
def test_history_is_oldest_first(memory_db):
    conversation_id, _ = get_or_create_conversation()
    save_turns(conversation_id, 2)

    assert get_history(conversation_id) == [
        ("user", "q1"), ("assistant", "r1"), ("user", "q2"), ("assistant", "r2"),
    ]


def test_history_keeps_only_the_last_6_messages(memory_db):
    conversation_id, _ = get_or_create_conversation()
    save_turns(conversation_id, 4)  # 8 messages

    assert memory.HISTORY_LIMIT == 6
    assert get_history(conversation_id) == [
        ("user", "q2"), ("assistant", "r2"),
        ("user", "q3"), ("assistant", "r3"),
        ("user", "q4"), ("assistant", "r4"),
    ]


def test_history_is_per_conversation(memory_db):
    a, _ = get_or_create_conversation()
    b, _ = get_or_create_conversation()
    save_message(a, "user", "only in a")

    assert get_history(b) == []


# (3) chat(): read history, answer with it, then save question and reply
@pytest.fixture
def fake_answer(monkeypatch):
    calls = []

    def respond(question, history=None):
        calls.append((question, list(history)))
        return rag.AnswerResult(f"reply to {question}", None)

    monkeypatch.setattr(rag, "respond", respond)
    return calls


def test_chat_passes_history_without_current_question_then_saves_both(memory_db, fake_answer):
    reply, session_id = rag.chat("q1")
    assert reply == "reply to q1"
    assert fake_answer[-1] == ("q1", [])

    reply, same_session = rag.chat("q2", session_id)

    assert same_session == session_id
    assert fake_answer[-1] == ("q2", [("user", "q1"), ("assistant", "reply to q1")])
    conversation_id, _ = get_or_create_conversation(session_id)
    assert messages(memory_db, conversation_id) == [
        ("user", "q1"), ("assistant", "reply to q1"),
        ("user", "q2"), ("assistant", "reply to q2"),
    ]


def test_chat_passes_at_most_6_history_messages(memory_db, fake_answer):
    _, session_id = rag.chat("q1")
    for q in ("q2", "q3", "q4"):
        rag.chat(q, session_id)

    rag.chat("q5", session_id)

    question, history = fake_answer[-1]
    assert question == "q5"
    assert [text for _, text in history] == [
        "q2", "reply to q2", "q3", "reply to q3", "q4", "reply to q4",
    ]


# (4) a history window cut in the middle must start with a user message for Gemini
def _capture_generate(monkeypatch, text="Sure, how can I help?"):
    seen = []

    def generate(contents):
        seen.append([(c.role, c.parts[0].text) for c in contents])
        return SimpleNamespace(function_calls=None, text=text)

    monkeypatch.setattr(rag, "_generate", generate)
    return seen


def test_window_cut_mid_pair_drops_leading_assistant_message(monkeypatch):
    seen = _capture_generate(monkeypatch)
    # 9 messages (a reply went missing): the last 6 start with the assistant's r2
    history = [
        ("user", "q1"), ("assistant", "r1"), ("user", "q2"),
        ("assistant", "r2"), ("user", "q3"), ("assistant", "r3"),
        ("user", "q4"), ("assistant", "r4"), ("user", "q5"),
    ]

    rag.answer("current question", history)

    assert seen[0] == [
        ("user", "q3"), ("model", "r3"), ("user", "q4"), ("model", "r4"),
        ("user", "q5"), ("user", "current question"),
    ]


def test_whole_window_is_kept_when_it_starts_with_user(monkeypatch):
    seen = _capture_generate(monkeypatch)
    history = [("user", "q1"), ("assistant", "r1")]

    rag.answer("q2", history)

    assert seen[0] == [("user", "q1"), ("model", "r1"), ("user", "q2")]


# (5) an error reply is saved like any other reply
def test_error_reply_is_saved(memory_db, monkeypatch):
    def broken_generate(contents):
        raise RuntimeError("network down")

    monkeypatch.setattr(rag, "_generate", broken_generate)

    reply, session_id = rag.chat("Is the K1 in stock?")

    assert reply == rag.ERROR_MESSAGE
    conversation_id, _ = get_or_create_conversation(session_id)
    assert messages(memory_db, conversation_id) == [
        ("user", "Is the K1 in stock?"), ("assistant", rag.ERROR_MESSAGE),
    ]
