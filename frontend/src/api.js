// Talks to the FastAPI backend: POST /chat {message, session_id?, visitor_id?}.
// Any failure (network, HTTP error, unexpected body) becomes one ChatError,
// so the page only has to handle one kind of problem.
import { isVisitorId } from "./storage";

export class ChatError extends Error {}

export async function sendMessage(message, sessionId, visitorId = null) {
  const body = { message };
  if (sessionId) body.session_id = sessionId;
  if (visitorId) body.visitor_id = visitorId;
  let data;
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new ChatError(`HTTP ${response.status}`);
    data = await response.json();
  } catch (error) {
    throw error instanceof ChatError ? error : new ChatError(error.message);
  }
  if (typeof data?.reply !== "string" || typeof data?.session_id !== "string") {
    throw new ChatError("Unexpected response");
  }
  return {
    reply: data.reply,
    sessionId: data.session_id,
    handoff: data.handoff === true,
    // null when missing or malformed: the page then keeps the id it already has
    visitorId: isVisitorId(data.visitor_id) ? data.visitor_id : null,
  };
}
