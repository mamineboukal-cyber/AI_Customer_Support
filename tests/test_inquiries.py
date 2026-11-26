"""raise_admin_inquiry: respond() reports the topic, chat() records it in the ledger
(unanswered_questions) and admin_inquiries. Runs on the throwaway test DB (conftest.py).
No Gemini call: _generate() plays a scripted model and _run_search() returns a fixed text."""
from types import SimpleNamespace

import pytest
from google.genai import types

import app.rag.answer as rag
from app.rag import inquiries
from app.rag.inquiries import normalize_question
from app.rag.memory import get_or_create_conversation

PROMISE = "We will check and come back to you."
SEARCH_RESULT = "Wireless Headphones X1: 499 MAD. Colors: black, white."


def call(name, **args):
    return SimpleNamespace(name=name, args=args)


@pytest.fixture
def model(monkeypatch):
    """model(turn, turn, ...): each turn is a list of tool calls or the final text.
    Returns the list of `contents` the model was called with."""
    seen = []

    def script(*turns):
        remaining = list(turns)

        def generate(contents):
            seen.append(list(contents))
            turn = remaining.pop(0)
            if isinstance(turn, str):
                return SimpleNamespace(function_calls=None, text=turn)
            content = types.Content(role="model", parts=[types.Part(text="(tool calls)")])
            return SimpleNamespace(
                function_calls=turn, text=None, candidates=[SimpleNamespace(content=content)]
            )

        monkeypatch.setattr(rag, "_generate", generate)
        return seen

    monkeypatch.setattr(rag, "_run_search", lambda query: SEARCH_RESULT)
    return script


def inquiry_turns(topic):
    return (
        [call("search_documents", query=topic)],
        [call("raise_admin_inquiry", topic=topic)],
        PROMISE,
    )


def ledger(db):
    return db.execute(
        "SELECT question, normalized_question, frequency, status "
        "FROM unanswered_questions ORDER BY id"
    ).fetchall()


def waiting(db):
    return db.execute(
        "SELECT unanswered_question_id, conversation_id, status, admin_answer, "
        "answered_at, delivered_at FROM admin_inquiries ORDER BY id"
    ).fetchall()


def counts(db):
    return db.execute(
        "SELECT (SELECT count(*) FROM conversations), (SELECT count(*) FROM messages), "
        "(SELECT count(*) FROM unanswered_questions), (SELECT count(*) FROM admin_inquiries)"
    ).fetchone()


def conversation_id(session_id):
    return get_or_create_conversation(session_id)[0]


# --- normalization -----------------------------------------------------------------

@pytest.mark.parametrize(
    "topic, expected",
    [
        ("Loyalty Program", "loyalty program"),
        ("  loyalty   program  ", "loyalty program"),
        ("loyalty\tprogram\n", "loyalty program"),
        ("Loyalty-Program!", "loyalty program"),
        ("loyalty_program?", "loyalty program"),
        ("Store location, Dubai.", "store location dubai"),
        ("X1 noise-cancelling", "x1 noise cancelling"),
        ("?!", ""),
    ],
)
def test_normalize_question(topic, expected):
    assert normalize_question(topic) == expected


# --- respond() / answer(): report, never write --------------------------------------

def test_respond_reports_topic_and_writes_nothing(memory_db, model):
    model(*inquiry_turns("loyalty program"))

    result = rag.respond("Do you have a loyalty program?")

    assert result == rag.AnswerResult(PROMISE, "loyalty program")
    assert counts(memory_db) == (0, 0, 0, 0)


def test_answer_still_returns_the_reply_string(memory_db, model):
    model(*inquiry_turns("loyalty program"))

    reply = rag.answer("Do you have a loyalty program?")

    assert isinstance(reply, str)
    assert reply == PROMISE
    assert counts(memory_db) == (0, 0, 0, 0)


def test_answer_without_inquiry_reports_no_topic(model):
    model([call("search_documents", query="X1 price")], "The X1 costs 499 MAD.")

    assert rag.respond("How much is the X1?") == rag.AnswerResult("The X1 costs 499 MAD.", None)


def test_inquiry_tool_result_tells_the_model_what_to_say(model):
    seen = model(*inquiry_turns("loyalty program"))

    rag.respond("Do you have a loyalty program?")

    tool_result = seen[2][-1].parts[0].function_response.response["result"]
    assert "come back" in tool_result
    assert "language" in tool_result
    assert "don't know" in tool_result  # told NOT to say it
    assert "invent" in tool_result


def test_transfer_in_the_same_turn_wins_over_inquiry(model):
    model([call("raise_admin_inquiry", topic="loyalty program"), call("transfer_to_human")])

    assert rag.respond("...") == rag.AnswerResult(rag.HANDOFF_MESSAGE, None)


def test_blank_topic_is_a_handoff(model):
    model([call("raise_admin_inquiry", topic=" ?! ")])

    assert rag.respond("...") == rag.AnswerResult(rag.HANDOFF_MESSAGE, None)


def test_handoff_reply_after_inquiry_drops_the_topic(model):
    model([call("raise_admin_inquiry", topic="loyalty program")], "")

    assert rag.respond("...") == rag.AnswerResult(rag.HANDOFF_MESSAGE, None)


# --- chat(): records the inquiry ----------------------------------------------------

def test_known_answer_records_no_inquiry(memory_db, model):
    model([call("search_documents", query="X1 price")], "The X1 costs 499 MAD.")

    reply, _ = rag.chat("How much is the X1?")

    assert reply == "The X1 costs 499 MAD."
    assert ledger(memory_db) == []
    assert waiting(memory_db) == []


def test_inquiry_creates_ledger_row_and_waiting_inquiry(memory_db, model):
    model(*inquiry_turns("Loyalty Program"))

    reply, session_id = rag.chat("Do you have a loyalty program?")

    assert reply == PROMISE
    assert ledger(memory_db) == [("Loyalty Program", "loyalty program", 1, "pending")]
    question_id = memory_db.execute("SELECT id FROM unanswered_questions").fetchone()[0]
    assert waiting(memory_db) == [
        (question_id, conversation_id(session_id), "waiting", None, None, None)
    ]
    # nothing else: one conversation, its two messages, one ledger row, one inquiry
    assert counts(memory_db) == (1, 2, 1, 1)


def test_two_conversations_same_topic_share_one_ledger_row(memory_db, model):
    model(*inquiry_turns("loyalty program"), *inquiry_turns("Loyalty  Program!"))

    _, first = rag.chat("Do you have a loyalty program?")
    _, second = rag.chat("Any loyalty points?")

    assert ledger(memory_db) == [("loyalty program", "loyalty program", 2, "pending")]
    rows = waiting(memory_db)
    assert [(c, s) for _, c, s, *_ in rows] == [
        (conversation_id(first), "waiting"),
        (conversation_id(second), "waiting"),
    ]
    assert rows[0][0] == rows[1][0]


def test_same_conversation_twice_counts_once(memory_db, model):
    model(*inquiry_turns("loyalty program"), *inquiry_turns("loyalty program"))

    reply, session_id = rag.chat("Do you have a loyalty program?")
    again, _ = rag.chat("So, a loyalty program?", session_id)

    assert again == PROMISE
    assert ledger(memory_db) == [("loyalty program", "loyalty program", 1, "pending")]
    assert len(waiting(memory_db)) == 1


def test_recording_failure_returns_error_and_writes_no_half_rows(memory_db, model, monkeypatch):
    model(*inquiry_turns("loyalty program"))

    def broken_insert(*args):
        raise RuntimeError("insert failed")

    # fails AFTER the ledger upsert ran: that upsert must be rolled back with it
    monkeypatch.setattr(inquiries, "_insert_inquiry", broken_insert)

    reply, session_id = rag.chat("Do you have a loyalty program?")

    assert reply == rag.ERROR_MESSAGE
    assert ledger(memory_db) == []
    assert waiting(memory_db) == []
    messages = memory_db.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id(session_id),),
    ).fetchall()
    assert messages == [
        ("user", "Do you have a loyalty program?"), ("assistant", rag.ERROR_MESSAGE),
    ]


# --- ledger rows that are no longer pending are never changed -----------------------

def _existing_row(db, status):
    db.execute(
        "INSERT INTO unanswered_questions "
        "(question, normalized_question, frequency, status, approved_answer) "
        "VALUES ('Loyalty program', 'loyalty program', 3, %s, %s)",
        (status, "Yes, 1 point per 10 MAD." if status == "resolved" else None),
    )
    return _snapshot(db)


def _snapshot(db):
    return db.execute(
        "SELECT id, question, frequency, status, approved_answer, reviewed_at, updated_at "
        "FROM unanswered_questions"
    ).fetchall()


def test_pending_row_counts_a_new_conversation(memory_db, model):
    _existing_row(memory_db, "pending")
    model(*inquiry_turns("loyalty program"))

    reply, _ = rag.chat("Do you have a loyalty program?")

    assert reply == PROMISE
    assert ledger(memory_db) == [("Loyalty program", "loyalty program", 4, "pending")]
    assert len(waiting(memory_db)) == 1


@pytest.mark.parametrize("status", ["reviewed", "resolved"])
def test_reviewed_or_resolved_row_is_untouched_but_inquiry_waits(memory_db, model, status):
    before = _existing_row(memory_db, status)
    model(*inquiry_turns("loyalty program"))

    reply, session_id = rag.chat("Do you have a loyalty program?")

    assert reply == PROMISE
    assert _snapshot(memory_db) == before
    assert [(c, s) for _, c, s, *_ in waiting(memory_db)] == [
        (conversation_id(session_id), "waiting")
    ]


def test_ignored_row_is_untouched_no_inquiry_and_no_promise(memory_db, model):
    before = _existing_row(memory_db, "ignored")
    model(*inquiry_turns("loyalty program"))

    reply, _ = rag.chat("Do you have a loyalty program?")

    assert reply == rag.HANDOFF_MESSAGE
    assert _snapshot(memory_db) == before
    assert waiting(memory_db) == []


# --- the digits heuristic does not apply after an inquiry ----------------------------

def test_promise_with_digits_after_inquiry_without_search_is_kept(memory_db, model):
    promise = "We will check and come back within 24 hours."
    model([call("raise_admin_inquiry", topic="loyalty program")], promise)

    reply, session_id = rag.chat("Do you have a loyalty program?")

    assert reply == promise
    assert ledger(memory_db) == [("loyalty program", "loyalty program", 1, "pending")]
    assert [(c, s) for _, c, s, *_ in waiting(memory_db)] == [
        (conversation_id(session_id), "waiting")
    ]


def test_digits_without_search_or_inquiry_are_still_a_handoff(model):
    model("The X1 costs 499 MAD.")

    assert rag.respond("How much is the X1?") == rag.HANDOFF


# --- tool-turn limit ------------------------------------------------------------------

def test_five_tool_turns_then_a_reply_is_answered(model):
    searches = [[call("search_documents", query=f"q{i}")] for i in range(5)]
    model(*searches, "The X1 costs 499 MAD.")

    assert rag.respond("...") == rag.AnswerResult("The X1 costs 499 MAD.", None)


def test_six_tool_turns_without_a_reply_is_a_handoff(model):
    searches = [[call("search_documents", query=f"q{i}")] for i in range(6)]
    model(*searches, "never reached")

    assert rag.respond("...") == rag.HANDOFF
