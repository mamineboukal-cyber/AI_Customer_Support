"""Admin answer path against Gemini, on the throwaway test DB.
Run with: pytest -m live -s -k test_admin_reply"""
import re
import time

import pytest

pytestmark = pytest.mark.live

ADMIN_ANSWER = "Yes, members get 10% off after the third order"

# (customer question, our earlier promise, words that must appear, words that must not)
CASES = {
    "english": (
        "Do you have a loyalty program?",
        "We will check and come back to you.",
        ["10%", "third", "order"],
        ["student", "free"],
    ),
    "french": (
        "Avez-vous un programme de fidélité ?",
        "Nous allons vérifier et revenir vers vous.",
        ["10", "%", "troisième", "commande"],
        ["student", "free", "étudiant", "gratuit"],
    ),
}


@pytest.mark.parametrize("case", CASES)
def test_admin_reply(memory_db, case):
    from app.rag.admin_answers import answer_inquiry

    question, promise, must, must_not = CASES[case]
    db = memory_db
    conversation = db.execute(
        "INSERT INTO conversations DEFAULT VALUES RETURNING id"
    ).fetchone()[0]
    for role, text in (("user", question), ("assistant", promise)):
        db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation, role, text),
        )
    ledger = db.execute(
        "INSERT INTO unanswered_questions (question, normalized_question) "
        "VALUES ('loyalty program', 'loyalty program') RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO admin_inquiries (unanswered_question_id, conversation_id) VALUES (%s, %s)",
        (ledger, conversation),
    )

    [result] = answer_inquiry(ledger, ADMIN_ANSWER)
    time.sleep(10)  # free-tier rate limit
    print(f"\n  customer: {question}\n  admin: {ADMIN_ANSWER}\n"
          f"  [{result.status}] {result.reply or result.error}")

    assert result.status == "delivered", result.error
    reply = result.reply.lower()
    assert all(w in reply for w in must), f"expected {must}, got: {result.reply}"
    assert not any(w in reply for w in must_not), f"forbidden word in: {result.reply}"
    assert set(re.findall(r"\d+", reply)) <= {"10"}, f"other numbers in: {result.reply}"
