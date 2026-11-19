import sys
import time

from app.rag.answer import answer, HANDOFF_MESSAGE, ERROR_MESSAGE

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
    ("كم سعر لوحة المفاتيح K1؟", ["699"]),
    ("Combien coûte la souris M1 ?", ["249"]),
    ("Livrez-vous à Marrakech ?", ["2", "5", "ouvrables"]),
    ("Puis-je retourner un produit après 20 jours ?", ["14"]),
    ("yo how much for the mouse", ["249"]),
    ("is the keyboard in stock?", ["8"]),
]

# questions that must be handed to a human agent
HANDOFF = [
    "Do you have a physical store in Dubai?",
    "Do you offer a 50% student discount?",
    "Do you have a loyalty program?",
    "Can you repair my iPhone?",
]

passed, failed, errors = 0, 0, 0


def check(question, ok_fn, expected):
    global passed, failed, errors
    reply = answer(question)
    time.sleep(5)  # stay under the free-tier limit of 15 requests per minute
    if reply == ERROR_MESSAGE:
        errors += 1
        print("ERROR", "|", question)
        print("      got:     ", reply)
    elif ok_fn(reply):
        passed += 1
        print("PASS ", "|", question)
        print("      got:     ", reply)
    else:
        failed += 1
        print("FAIL ", "|", question)
        print("      expected:", expected)
        print("      got:     ", reply)


for question, words in CONTAINS:
    check(question, lambda r, w=words: all(x in r.lower() for x in w), f"contains {words}")

for question in HANDOFF:
    check(question, lambda r: r == HANDOFF_MESSAGE, "handoff message")

print(f"\npassed={passed} failed={failed} errors={errors}")
sys.exit(1 if failed else 0)
