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
    ("Can I pay using PayPal?", ["cash on delivery", "card"]),
    ("شحال ثمن السماعات X1؟", ["499"]),
    ("ch7al kaydir keyboard K1?", ["699"]),
    ("Combien coûte la souris M1 ?", ["249"]),
    # the numbers and the city, not a French word ("ouvrables" / "ouvrés" both occur)
    ("Livrez-vous à Marrakech ?", ["2", "5", "marrakech"]),
    ("Puis-je retourner un produit après 20 jours ?", ["14"]),
    ("yo how much for the mouse", ["249"]),
    ("is the keyboard in stock?", ["8"]),
]


# Outside a closed list in the documents: "we do not offer it" plus what we do offer,
# and no inquiry. (question, words that must appear in the answer)
NOT_OFFERED = [
    ("Do you have a red version of the X1?", ["black"]),
    ("Can I pay with Bitcoin?", ["cash on delivery", "card"]),
]

# Not recorded in the documents: the bot raises an admin inquiry instead of guessing.
INQUIRY = [
    "Do you have a physical store in Dubai?",
    "Do you offer a 50% student discount?",
    "Do you have a loyalty program?",
    "Does the Wireless Headphones X1 have noise cancelling?",
    "Can you repair my iPhone?",  # a service category the documents do not record
]

# Angry complaint, off-topic, or personal/emotional: hand off to a human.
HANDOFF = [
    "my delivery is late, this is unacceptable, I want my money back",
    "i love you",
]

# A real greeting or thank-you: a polite reply, no handoff and no inquiry.
POLITE = [
    "hello",
    "thanks a lot",
]


@pytest.fixture(scope="module")
def rag():
    import app.rag.answer

    return app.rag.answer


def ask_full(rag, question):
    """respond(): the reply and the inquiry topic (None when no inquiry was raised)."""
    result = rag.respond(question)
    time.sleep(10)  # stay under the free-tier limit of 15 requests per minute
    print(f"\n  Q: {question}\n  A: {result.reply}\n  inquiry: {result.inquiry_topic}")
    if result.reply == rag.ERROR_MESSAGE:
        pytest.skip("Gemini error")
    return result


def ask(rag, question):
    return ask_full(rag, question).reply


@pytest.mark.parametrize("question,words", CONTAINS, ids=[q for q, _ in CONTAINS])
def test_answer_contains(rag, question, words):
    reply = ask(rag, question)
    assert all(w in reply.lower() for w in words), f"expected {words}, got: {reply}"


@pytest.mark.parametrize("question,words", NOT_OFFERED, ids=[q for q, _ in NOT_OFFERED])
def test_not_offered(rag, question, words):
    result = ask_full(rag, question)
    assert result.inquiry_topic is None, f"raised an inquiry: {result.inquiry_topic}"
    assert all(w in result.reply.lower() for w in words), f"expected {words}, got: {result.reply}"


@pytest.mark.parametrize("question", INQUIRY)
def test_inquiry(rag, question):
    result = ask_full(rag, question)
    assert result.inquiry_topic, f"no inquiry, got: {result.reply}"
    assert result.reply != rag.HANDOFF_MESSAGE


@pytest.mark.parametrize("question", HANDOFF)
def test_handoff(rag, question):
    reply = ask(rag, question)
    assert reply == rag.HANDOFF_MESSAGE, f"got: {reply}"


@pytest.mark.parametrize("question", POLITE)
def test_polite_reply(rag, question):
    result = ask_full(rag, question)
    assert result.reply != rag.HANDOFF_MESSAGE
    assert result.inquiry_topic is None, f"raised an inquiry: {result.inquiry_topic}"
