import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.search import search, has_answer

load_dotenv()

HANDOFF_MESSAGE = "I don't know. Let me connect you to a human agent."
ERROR_MESSAGE = "Sorry, we are having a technical problem. Let me connect you to a human agent."

SYSTEM_PROMPT = """You are a customer support employee for MoroccoTech, an electronics store in Morocco.
Your mission is to help customers by answering their questions.

With each question, you will receive some information chunks from the store's documents.

Rules:
- Answer ONLY using the provided information. Never use outside knowledge and never invent policies, prices or delays.
- If the answer is not in the provided information, say you don't have that information and guide the customer to a human agent.
- Reply in the same language as the customer's question.
- Keep answers short, clear and polite.
"""

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=15000),
)


def answer(question):
    results = search(question)

    if not has_answer(results):
        return HANDOFF_MESSAGE

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
            model="gemini-3.8-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print("Gemini error:", e)
        return ERROR_MESSAGE


if __name__ == "__main__":
    question = input("what is your question? ")
    print(answer(question))