import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors

from app.rag.memory import get_history, get_or_create_conversation, save_message
from app.rag.search import search

load_dotenv()

HANDOFF_MESSAGE = "I don't know. Let me connect you to a human agent."
ERROR_MESSAGE = "Sorry, we are having a technical problem. Let me connect you to a human agent."
RETRY_CODES = (503, 504)
MAX_ATTEMPTS = 3
RETRY_WAIT = (2, 4)
MODEL = "gemini-3.5-flash-lite"
MAX_TURNS = 4
HISTORY_LIMIT = 6

SYSTEM_PROMPT = """You are a customer support employee for MoroccoTech, an electronics store in Morocco.

You have two tools:
- search_documents: searches the store's documents (products, prices, stock, colors, warranty, delivery, returns, payment).
- transfer_to_human: hands the customer to a human agent.

Rules:
- If the customer's message is only a greeting or a thank-you, reply politely and ask how you can help. Do not use any tool.
- For any question about the store, call search_documents BEFORE answering. Answer ONLY from the search results. Never use outside knowledge and never invent prices, stock, policies or delays.
- Use the conversation so far to understand what the customer refers to (for example "it" or "that one"), and put the product name in your search query.
- The documents are written in English. Write search queries in English, even if the customer writes in French, Arabic or Darija.
- If the question has several parts, search for each part separately.
- If the results look weak or empty, try one different query before giving up.
- The search results are the store's complete catalog. If a product, color, version or payment method is not mentioned, say clearly that we do not offer it and state what we do offer.
- If you cannot find the answer after searching, or the message is not about the store, call transfer_to_human.
- Reply in the language of the customer's message (including Darija). Keep answers short, clear and polite.
"""

search_declaration = types.FunctionDeclaration(
    name="search_documents",
    description=(
        "Search MoroccoTech's documents (products, prices, stock, colors, warranty, "
        "delivery, returns, payment, FAQ). Returns the most relevant text chunks."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="A short, clear English search query about one topic.",
            )
        },
        required=["query"],
    ),
)

transfer_declaration = types.FunctionDeclaration(
    name="transfer_to_human",
    description=(
        "Hand the customer to a human agent. Use it only when the documents "
        "do not contain the answer after searching, or the message is not about the store."
    ),
)

config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[search_declaration, transfer_declaration])],
    # we run the tool loop ourselves
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

_client = None


def get_client():
    # created on first use, so importing this module needs no API key
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=15000),
        )
    return _client


def _text_content(role, text):
    return types.Content(role=role, parts=[types.Part(text=text)])


def _run_search(query):
    print("  [search]", query)
    results = search(query)
    return "\n\n".join(text for text, distance in results) or "No results found."


def _generate(contents):
    for attempt in range(MAX_ATTEMPTS):
        try:
            return get_client().models.generate_content(
                model=MODEL,
                contents=contents,
                config=config,
            )
        except errors.APIError as e:
            last_attempt = attempt == MAX_ATTEMPTS - 1
            if e.code not in RETRY_CODES or last_attempt:
                raise
            print(f"Gemini {e.code}, retrying in {RETRY_WAIT[attempt]}s...")
            time.sleep(RETRY_WAIT[attempt])

def answer(question, history=None):
    """Answer one customer message. `history` is a list of (role, text) pairs,
    role being "user" or "assistant". Touches no database apart from the search."""
    contents = []
    for role, text in (history or [])[-HISTORY_LIMIT:]:
        gemini_role = "model" if role == "assistant" else "user"
        # a window cut in the middle of a pair can start with an assistant message
        if not contents and gemini_role == "model":
            continue
        contents.append(_text_content(gemini_role, text))
    contents.append(_text_content("user", question))

    searched = False

    try:
        for _ in range(MAX_TURNS):
            response = _generate(contents)

            calls = response.function_calls
            if not calls:
                reply = (response.text or "").strip()
                if not reply or "HANDOFF" in reply:
                    return HANDOFF_MESSAGE
                # heuristic: a reply with numbers but no search is probably invented
                if not searched and any(ch.isdigit() for ch in reply):
                    return HANDOFF_MESSAGE
                return reply

            # keep the model's turn exactly as it came back
            contents.append(response.candidates[0].content)

            result_parts = []
            for call in calls:
                if call.name == "transfer_to_human":
                    return HANDOFF_MESSAGE
                if call.name == "search_documents":
                    searched = True
                    result = _run_search((call.args or {}).get("query", ""))
                else:
                    result = "Unknown tool."
                result_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"result": result},
                    )
                )

            contents.append(types.Content(role="user", parts=result_parts))

        # the model kept asking for tools without giving an answer
        return HANDOFF_MESSAGE

    except Exception as e:
        print("Gemini error:", e)
        return ERROR_MESSAGE


def chat(question, session_id=None):
    """One turn of a stored conversation: read history, answer, save both messages.
    Returns (reply, session_id)."""
    conversation_id, session_id = get_or_create_conversation(session_id)
    history = get_history(conversation_id, HISTORY_LIMIT)
    reply = answer(question, history)
    # saved after answering, so `history` never contains the current question
    save_message(conversation_id, "user", question)
    save_message(conversation_id, "assistant", reply)
    return reply, session_id


if __name__ == "__main__":
    session_id = None
    while True:
        question = input("you: ")
        if not question:
            break
        reply, session_id = chat(question, session_id)
        print("bot:", reply)
    if session_id:
        print("conversation:", session_id)