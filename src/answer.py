import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.search import search

load_dotenv()

HANDOFF_MESSAGE = "I don't know. Let me connect you to a human agent."
ERROR_MESSAGE = "Sorry, we are having a technical problem. Let me connect you to a human agent."

SYSTEM_PROMPT = """You are a customer support employee for MoroccoTech, an electronics store in Morocco.
Your mission is to help customers by answering their questions.

With each question, you will receive some information chunks from the store's documents.

Rules:
- If the customer's message is a greeting or a thank-you, reply politely and ask how you can help.
- If it is a question about the store, answer ONLY using the provided information. Never use outside knowledge and never invent policies, prices or delays.
- The provided information is the store's complete catalog. If the customer asks about a product, color, version or payment method that is not mentioned, say clearly that we do not offer it and state what we do offer (for example the available colors or the accepted payment methods). Always name the actual accepted payment methods.
- Otherwise, if the answer is not in the provided information, or the message is not about the store, reply with exactly the single word HANDOFF and nothing else.
- Reply in the language of the customer's message (an English question gets an English answer), even if the information is written in another language.
- Keep answers short, clear and polite.
"""

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=15000),
)


def answer(question):
    results = search(question)

    context = ""
    for text, distance in results:
        context = context + text + "\n\n"

    prompt = f"""{SYSTEM_PROMPT}

Information from the store's documents:
{context}

Customer question: {question}
"""

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        text = response.text.strip()
        if "HANDOFF" in text:
            return HANDOFF_MESSAGE
        return text
    except Exception as e:
        print("Gemini error:", e)
        return ERROR_MESSAGE


if __name__ == "__main__":
    question = input("what is your question? ")
    print(answer(question))