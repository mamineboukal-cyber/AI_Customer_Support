"""End-to-end eval against Gemini. Run with: pytest -m live (about 2 minutes)."""
import time

import pytest

pytestmark = pytest.mark.live

# (question, words that must appear in the answer)
CONTAINS = [
    ("How much is the Wireless Headphones X1?", ["499"]),
    ("How much is the Mechanical Keyboard K1?", ["699"]),
    ("Is the Mechanical Keyboard K1 available?", ["yes"]),
    ("How long does delivery take to Tangier?", ["business days"]),
    ("Can I pay with cash on delivery?", ["cash on delivery"]),
    ("Can I return a product after 10 days?", ["14"]),
    ("Can I return a product after 30 days?", ["14"]),
    ("How long is the warranty for the X1?", ["12"]),
    ("Do you offer free shipping?", ["500"]),
    ("Can I return opened headphones?", ["defective"]),
    ("Do you have a red version of the X1?", ["black"]),
    ("Can I pay with Bitcoin?", ["cash on delivery", "card"]),
    ("Can I pay using PayPal?", ["cash on delivery", "card"]),
    ("شحال ثمن السماعات X1؟", ["499"]),
    ("ch7al kaydir keyboard K1?", ["699"]),
    ("Combien coûte la souris M1 ?", ["249"]),
    ("Livrez-vous à Marrakech ?", ["2", "5", "ouvrables"]),
    ("Puis-je retourner un produit après 20 jours ?", ["14"]),
    ("yo how much for the mouse", ["249"]),
    ("is the keyboard in stock?", ["8"]),
]


HANDOFF = [
    "Do you have a physical store in Dubai?",
    "Do you offer a 50% student discount?",
    "Do you have a loyalty program?",
    "Can you repair my iPhone?",
]


@pytest.fixture(scope="module")
def rag():
    import app.rag.answer

    return app.rag.answer


def ask(rag, question):
    reply = rag.answer(question)
    time.sleep(10)  # stay under the free-tier limit of 15 requests per minute
    print(f"\n  Q: {question}\n  A: {reply}")
    if reply == rag.ERROR_MESSAGE:
        pytest.skip("Gemini error")
    return reply


@pytest.mark.parametrize("question,words", CONTAINS, ids=[q for q, _ in CONTAINS])
def test_answer_contains(rag, question, words):
    reply = ask(rag, question)
    assert all(w in reply.lower() for w in words), f"expected {words}, got: {reply}"


@pytest.mark.parametrize("question", HANDOFF)
def test_handoff(rag, question):
    reply = ask(rag, question)
    assert reply == rag.HANDOFF_MESSAGE, f"got: {reply}"
