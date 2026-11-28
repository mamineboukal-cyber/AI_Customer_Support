"""Admin answer path: list waiting inquiries, answer one ledger question for every
conversation waiting on it. Throwaway test DB (conftest.py); the model is scripted,
no Gemini call."""
import json
from types import SimpleNamespace

import pytest

import app.rag.answer as rag
from app import admin
from app.rag import admin_answers
from app.rag.admin_answers import AdminAnswerError, answer_inquiry, list_waiting

ADMIN_ANSWER = "Yes, members get 10% off after the third order."


@pytest.fixture
def model(monkeypatch):
    """model(out, out, ...): one output per call, in order. An output is a dict (sent
    back as the JSON text), a str (raw text) or an Exception (raised).
    Returns the list of (contents, config) the model was called with."""
    calls = []

    def script(*outputs):
        remaining = list(outputs)

        def generate(contents, config=None):
            calls.append((list(contents), config))
            out = remaining.pop(0)
            if isinstance(out, Exception):
                raise out
            if callable(out):
                out = out()
            text = json.dumps(out) if isinstance(out, dict) else out
            return SimpleNamespace(text=text, function_calls=None)

        monkeypatch.setattr(rag, "_generate", generate)
        return calls

    return script


def reply(text, covered=True):
    return {"covered": covered, "reply": text}


def _conversation(db, *messages):
    cid = db.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id").fetchone()[0]
    for role, content in messages:
        # Assistant messages need a reply_kind (0006); these are the inquiry promises.
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, reply_kind) "
            "VALUES (%s, %s, %s, %s)",
            (cid, role, content, "inquiry" if role == "assistant" else None),
        )
    return cid


def _ledger(db, topic="loyalty program", status="pending", approved=None, frequency=1):
    return db.execute(
        "INSERT INTO unanswered_questions "
        "(question, normalized_question, frequency, status, approved_answer) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (topic, topic, frequency, status, approved),
    ).fetchone()[0]


def _inquiry(db, ledger_id, conversation_id, status="waiting"):
    extra = {
        "waiting": ("NULL", "NULL", "NULL"),
        "answered": ("'old'", "now()", "NULL"),
        "delivered": ("'old'", "now()", "now()"),
    }[status]
    return db.execute(
        "INSERT INTO admin_inquiries (unanswered_question_id, conversation_id, status, "
        f"admin_answer, answered_at, delivered_at) VALUES (%s, %s, %s, {', '.join(extra)}) "
        "RETURNING id",
        (ledger_id, conversation_id, status),
    ).fetchone()[0]


ASKED = [
    ("user", "Do you have a loyalty program?"),
    ("assistant", "We will check and come back to you."),
]


@pytest.fixture
def two_waiting(memory_db):
    """One ledger row, two conversations waiting on it (English and French)."""
    ledger_id = _ledger(memory_db, frequency=2)
    a = _conversation(memory_db, *ASKED)
    b = _conversation(
        memory_db,
        ("user", "Avez-vous un programme de fidélité ?"),
        ("assistant", "Nous allons vérifier et revenir vers vous."),
    )
    ia, ib = _inquiry(memory_db, ledger_id, a), _inquiry(memory_db, ledger_id, b)
    return SimpleNamespace(db=memory_db, ledger_id=ledger_id, a=a, b=b, ia=ia, ib=ib)


def inquiries(db):
    return db.execute(
        "SELECT id, status, admin_answer, answered_at IS NOT NULL, delivered_at IS NOT NULL "
        "FROM admin_inquiries ORDER BY id"
    ).fetchall()


def messages(db, conversation_id):
    return db.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()


def snapshot(db):
    return (
        db.execute("SELECT * FROM unanswered_questions ORDER BY id").fetchall(),
        db.execute("SELECT * FROM admin_inquiries ORDER BY id").fetchall(),
        db.execute("SELECT * FROM messages ORDER BY id").fetchall(),
    )


# --- listing ------------------------------------------------------------------------

def test_list_waiting_returns_only_waiting_inquiries(two_waiting):
    t = two_waiting
    other = _ledger(t.db, topic="store in dubai")
    _inquiry(t.db, other, _conversation(t.db), status="delivered")
    _inquiry(t.db, other, _conversation(t.db), status="answered")

    rows = list_waiting()

    assert [(r.inquiry_id, r.ledger_id, r.topic, r.frequency, r.conversation_id)
            for r in rows] == [
        (t.ia, t.ledger_id, "loyalty program", 2, t.a),
        (t.ib, t.ledger_id, "loyalty program", 2, t.b),
    ]
    assert all(r.created_at is not None for r in rows)


# --- answering ----------------------------------------------------------------------

def test_every_waiting_conversation_gets_a_saved_reply_and_is_delivered(two_waiting, model):
    t = two_waiting
    model(
        reply("Yes! Members get 10% off after their third order."),
        reply("Oui ! Les membres ont 10% de réduction après la troisième commande."),
    )

    results = answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert [(r.conversation_id, r.status, r.reply) for r in results] == [
        (t.a, "delivered", "Yes! Members get 10% off after their third order."),
        (t.b, "delivered",
         "Oui ! Les membres ont 10% de réduction après la troisième commande."),
    ]
    assert inquiries(t.db) == [
        (t.ia, "delivered", ADMIN_ANSWER, True, True),
        (t.ib, "delivered", ADMIN_ANSWER, True, True),
    ]
    assert messages(t.db, t.a)[-1] == (
        "assistant", "Yes! Members get 10% off after their third order.")
    assert messages(t.db, t.b)[-1] == (
        "assistant", "Oui ! Les membres ont 10% de réduction après la troisième commande.")
    # The delivered answer is an ordinary answer for the statistics (0006).
    assert t.db.execute(
        "SELECT reply_kind FROM messages WHERE conversation_id IN (%s, %s) "
        "AND role = 'assistant' ORDER BY id DESC LIMIT 2",
        (t.a, t.b),
    ).fetchall() == [("normal",), ("normal",)]


def test_model_sees_the_conversation_and_the_admin_answer(two_waiting, model):
    calls = model(reply("ok 10"), reply("ok 10"))

    answer_inquiry(two_waiting.ledger_id, ADMIN_ANSWER)

    contents, config = calls[0]
    text = " ".join(part.text for c in contents for part in c.parts)
    assert "Do you have a loyalty program?" in text
    assert "We will check and come back to you." in text
    assert ADMIN_ANSWER in text
    assert "loyalty program" in text  # the ledger topic
    assert config is admin_answers.REPLY_CONFIG
    assert "Avez-vous" not in text  # only this conversation's messages


def test_one_model_failure_does_not_block_the_other(two_waiting, model):
    t = two_waiting
    model(RuntimeError("Gemini down"), reply("Oui, 10% après la troisième commande."))

    results = answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert [(r.conversation_id, r.status) for r in results] == [
        (t.a, "failed"), (t.b, "delivered"),
    ]
    assert "Gemini down" in results[0].error
    assert results[0].reply is None
    assert inquiries(t.db) == [
        (t.ia, "answered", ADMIN_ANSWER, True, False),
        (t.ib, "delivered", ADMIN_ANSWER, True, True),
    ]
    assert messages(t.db, t.a) == ASKED  # nothing saved for the failed one


def test_admin_answer_that_does_not_cover_the_question_is_not_sent(two_waiting, model):
    t = two_waiting
    model(reply("", covered=False), reply("Oui, 10% après la troisième commande."))

    results = answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert results[0].status == "not_covered"
    assert results[0].reply is None
    assert inquiries(t.db)[0] == (t.ia, "answered", ADMIN_ANSWER, True, False)
    assert messages(t.db, t.a) == ASKED


@pytest.mark.parametrize(
    "bad",
    [
        reply("Members get 15% off after the third order."),  # a number not in the answer
        reply("   "),  # empty reply
        "not json",
    ],
    ids=["new-number", "empty-reply", "not-json"],
)
def test_unusable_reply_is_a_failure_and_not_sent(two_waiting, model, bad):
    t = two_waiting
    model(bad, reply("Oui, 10% après la troisième commande."))

    results = answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert [r.status for r in results] == ["failed", "delivered"]
    assert results[0].error
    assert inquiries(t.db)[0] == (t.ia, "answered", ADMIN_ANSWER, True, False)
    assert messages(t.db, t.a) == ASKED


def test_no_double_send(two_waiting, model):
    t = two_waiting
    model(reply("Yes, 10% after the third order."), reply("Oui, 10%."))
    answer_inquiry(t.ledger_id, ADMIN_ANSWER)
    before = snapshot(t.db)

    with pytest.raises(AdminAnswerError, match="no waiting inquiries"):
        answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert snapshot(t.db) == before


def test_inquiry_delivered_meanwhile_is_skipped(two_waiting, model):
    t = two_waiting

    def delivered_by_someone_else():
        # another run delivers conversation a while the model is answering it
        t.db.execute(
            "UPDATE admin_inquiries SET status = 'delivered', admin_answer = 'other', "
            "answered_at = now(), delivered_at = now() WHERE id = %s",
            (t.ia,),
        )
        return reply("Yes, 10% after the third order.")

    model(delivered_by_someone_else, reply("Oui, 10%."))

    results = answer_inquiry(t.ledger_id, ADMIN_ANSWER)

    assert [r.status for r in results] == ["skipped", "delivered"]
    assert messages(t.db, t.a) == ASKED
    assert inquiries(t.db)[0][1:3] == ("delivered", "other")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_admin_answer_writes_nothing(two_waiting, model, text):
    calls = model()
    before = snapshot(two_waiting.db)

    with pytest.raises(AdminAnswerError, match="empty"):
        answer_inquiry(two_waiting.ledger_id, text)

    assert snapshot(two_waiting.db) == before
    assert calls == []


def test_unknown_ledger_id_is_a_clear_error(two_waiting, model):
    before = snapshot(two_waiting.db)

    with pytest.raises(AdminAnswerError, match="ledger question 999 does not exist"):
        answer_inquiry(999, ADMIN_ANSWER)

    assert snapshot(two_waiting.db) == before


def test_ledger_id_without_waiting_inquiries_is_a_clear_error(memory_db, model):
    ledger_id = _ledger(memory_db)

    with pytest.raises(AdminAnswerError, match=f"no waiting inquiries for ledger question {ledger_id}"):
        answer_inquiry(ledger_id, ADMIN_ANSWER)

    assert memory_db.execute("SELECT status FROM unanswered_questions").fetchone() == ("pending",)


def test_ledger_ends_reviewed_with_approved_answer_empty(two_waiting, model):
    model(reply("Yes, 10%."), RuntimeError("down"))

    answer_inquiry(two_waiting.ledger_id, ADMIN_ANSWER)

    row = two_waiting.db.execute(
        "SELECT status, approved_answer, reviewed_at IS NOT NULL, frequency "
        "FROM unanswered_questions"
    ).fetchone()
    assert row == ("reviewed", None, True, 2)


def test_resolved_ledger_row_is_not_downgraded(memory_db, model):
    ledger_id = _ledger(memory_db, status="resolved", approved="Approved text.")
    _inquiry(memory_db, ledger_id, _conversation(memory_db, *ASKED))
    model(reply("Yes, 10%."))

    answer_inquiry(ledger_id, ADMIN_ANSWER)

    assert memory_db.execute(
        "SELECT status, approved_answer FROM unanswered_questions"
    ).fetchone() == ("resolved", "Approved text.")


# --- command line -------------------------------------------------------------------

def test_cli_list(two_waiting, capsys):
    assert admin.main(["list"]) == 0

    out = capsys.readouterr().out
    assert "loyalty program" in out
    assert str(two_waiting.ia) in out and str(two_waiting.ib) in out


def test_cli_answer_prints_the_replies(two_waiting, model, capsys):
    model(reply("Yes, 10% after the third order."), RuntimeError("down"))

    code = admin.main(["answer", str(two_waiting.ledger_id), ADMIN_ANSWER])

    out = capsys.readouterr().out
    assert "Yes, 10% after the third order." in out
    assert "failed" in out and "down" in out
    assert code == 1  # not everything was delivered


def test_cli_answer_error_exits_nonzero(two_waiting, model, capsys):
    assert admin.main(["answer", "999", ADMIN_ANSWER]) == 2
    assert "does not exist" in capsys.readouterr().err
