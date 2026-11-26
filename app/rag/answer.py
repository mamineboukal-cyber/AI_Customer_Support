import os
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors

from app.rag.inquiries import normalize_question, record_inquiry
from app.rag.memory import get_history, get_or_create_conversation, save_message
from app.rag.search import search

load_dotenv()

HANDOFF_MESSAGE = "I don't know. Let me connect you to a human agent."
ERROR_MESSAGE = "Sorry, we are having a technical problem. Let me connect you to a human agent."
RETRY_CODES = (503, 504)
MAX_ATTEMPTS = 3
RETRY_WAIT = (2, 4)
MODEL = "gemini-3.5-flash-lite"
MAX_TURNS = 6
HISTORY_LIMIT = 6

SYSTEM_PROMPT = """You are a customer support employee for MoroccoTech, an electronics store in Morocco.

You have three tools:
- search_documents: searches the store's documents (products, prices, stock, colors, warranty, delivery, returns, payment).
- raise_admin_inquiry: asks the store's team for an answer the documents do not have; we come back to the customer later.
- transfer_to_human: hands the customer to a human agent.

Rules:
- If the customer's message is only a greeting or a thank-you, reply politely and ask how you can help. Do not use any tool.
- For any question about the store, call search_documents BEFORE answering. Answer ONLY from the search results. Never use outside knowledge and never invent prices, stock, features, policies or delays.
- Use the conversation so far to understand what the customer refers to (for example "it" or "that one"), and put the product name in your search query.
- The documents are written in English. Write search queries in English, even if the customer writes in French, Arabic or Darija.
- If the question has several parts, search for each part separately.
- If the results look weak or empty, try one different query before deciding.

After searching, decide:
1. The answer is in the documents: answer it.
2. The documents give a closed list (the products we sell, their colors, the accepted payment methods, the return window, the delivery cities) and the customer asks for something outside that list (for example a red X1 when only other colors are listed, paying with Bitcoin, a washing machine): say clearly that we do not offer it and state what we do offer.
3. The product or topic is in the documents but the specific detail asked is not recorded (for example noise cancelling or battery life of a product we sell): never say that we do not offer it and never guess. Call raise_admin_inquiry.
4. The topic is not covered by the documents at all (for example a store location, discounts, a loyalty program): call raise_admin_inquiry.
5. The customer is angry, makes a complaint, or the message is not about the store: call transfer_to_human.

- After raise_admin_inquiry, do what its result says. Never say "I don't know".
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

inquiry_declaration = types.FunctionDeclaration(
    name="raise_admin_inquiry",
    description=(
        "Ask the store's team to answer a question the documents do not answer: a detail "
        "that is not recorded about something we sell, or a topic the documents do not "
        "cover. We come back to the customer later."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "topic": types.Schema(
                type=types.Type.STRING,
                description=(
                    "A short English topic of what the customer wants to know, "
                    "for example 'loyalty program' or 'X1 noise cancelling'."
                ),
            )
        },
        required=["topic"],
    ),
)

transfer_declaration = types.FunctionDeclaration(
    name="transfer_to_human",
    description=(
        "Hand the customer to a human agent. Use it only when the customer is angry, "
        "makes a complaint, or the message is not about the store."
    ),
)

INQUIRY_RESULT = (
    "Inquiry noted. Tell the customer, in the language of their message, that we will "
    "check and come back to them. Do not invent or guess any answer, and do not say "
    "that you don't know."
)

config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[
        types.Tool(
            function_declarations=[search_declaration, inquiry_declaration, transfer_declaration]
        )
    ],
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

@dataclass(frozen=True)
class AnswerResult:
    reply: str
    # set only when the model raised an inquiry and the reply promises to come back
    inquiry_topic: str | None = None


HANDOFF = AnswerResult(HANDOFF_MESSAGE)


def respond(question, history=None):
    """Answer one customer message. `history` is a list of (role, text) pairs,
    role being "user" or "assistant". Returns an AnswerResult. Touches no database
    apart from the search: recording an inquiry is chat()'s job."""
    contents = []
    for role, text in (history or [])[-HISTORY_LIMIT:]:
        gemini_role = "model" if role == "assistant" else "user"
        # a window cut in the middle of a pair can start with an assistant message
        if not contents and gemini_role == "model":
            continue
        contents.append(_text_content(gemini_role, text))
    contents.append(_text_content("user", question))

    searched = False
    topic = None

    try:
        for _ in range(MAX_TURNS):
            response = _generate(contents)

            calls = response.function_calls
            if not calls:
                reply = (response.text or "").strip()
                if not reply or "HANDOFF" in reply:
                    return HANDOFF
                # heuristic: a reply with numbers but no search is probably invented;
                # not after an inquiry, where it is a promise ("within 24 hours")
                if not searched and topic is None and any(ch.isdigit() for ch in reply):
                    return HANDOFF
                return AnswerResult(reply, topic)

            if any(call.name == "transfer_to_human" for call in calls):
                return HANDOFF

            # keep the model's turn exactly as it came back
            contents.append(response.candidates[0].content)

            result_parts = []
            for call in calls:
                args = call.args or {}
                if call.name == "search_documents":
                    searched = True
                    result = _run_search(args.get("query", ""))
                elif call.name == "raise_admin_inquiry":
                    asked = (args.get("topic") or "").strip()
                    if not normalize_question(asked):
                        return HANDOFF
                    # one inquiry per message: the first topic is kept
                    topic = topic or asked
                    result = INQUIRY_RESULT
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
        return HANDOFF

    except Exception as e:
        print("Gemini error:", e)
        return AnswerResult(ERROR_MESSAGE)


def answer(question, history=None):
    """The reply text only (see respond())."""
    return respond(question, history).reply


def chat(question, session_id=None):
    """One turn of a stored conversation: read history, answer, save both messages.
    Returns (reply, session_id)."""
    conversation_id, session_id = get_or_create_conversation(session_id)
    history = get_history(conversation_id, HISTORY_LIMIT)
    result = respond(question, history)
    reply = result.reply
    if result.inquiry_topic:
        try:
            if not record_inquiry(conversation_id, result.inquiry_topic):
                # the admin ignores this question: do not promise to come back
                reply = HANDOFF_MESSAGE
        except Exception as e:
            print("Could not record inquiry:", e)
            reply = ERROR_MESSAGE
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