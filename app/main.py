from fastapi import FastAPI
from uuid import UUID
from pydantic import BaseModel, Field

from app.admin_api import router as admin_router
from app.rag.answer import chat_turn

app = FastAPI()
# No authentication yet: see README before exposing these routes.
app.include_router(admin_router, prefix="/admin")

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Both ids are created by the server: a missing or unknown one gets a new id,
    # returned in the response; a malformed one is a 422.
    session_id: UUID | None = None
    visitor_id: UUID | None = None


@app.get("/health")
def health():
    return {"message": "ok!"}

@app.post("/chat")
def chat_endpoint(body: ChatRequest):
    turn = chat_turn(body.message, body.session_id, body.visitor_id)
    return {
        "reply": turn.reply,
        "session_id": str(turn.session_id),
        "visitor_id": str(turn.visitor_id),
        "reply_kind": turn.reply_kind,
        "handoff": turn.reply_kind == "handoff",
        "inquiry": turn.reply_kind == "inquiry",
    }
