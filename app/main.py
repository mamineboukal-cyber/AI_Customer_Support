from fastapi import FastAPI
from uuid import UUID
from pydantic import BaseModel, Field

from app.rag.answer import HANDOFF_MESSAGE, chat

app = FastAPI()

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: UUID | None = None


@app.get("/health")
def health():
    return {"message": "ok!"}

@app.post("/chat")
def chat_endpoint(body: ChatRequest):
    reply, session_id = chat(body.message, body.session_id)
    return {
        "reply": reply,
        "session_id": str(session_id),
        "handoff": reply == HANDOFF_MESSAGE,
    }
