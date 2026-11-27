// Talks to the FastAPI backend: POST /chat {message, session_id?}.
// Any failure (network, HTTP error, unexpected body) becomes one ChatError,
// so the page only has to handle one kind of problem.
export class ChatError extends Error {}

export async function sendMessage(message, sessionId) {
  const body = sessionId ? { message, session_id: sessionId } : { message };
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
  return { reply: data.reply, sessionId: data.session_id, handoff: data.handoff === true };
}
