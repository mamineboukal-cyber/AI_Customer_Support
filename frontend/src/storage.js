// Saves the conversation in the browser so a reload restores it.
// localStorage can be full, blocked (private mode) or hold old data, so
// every access is wrapped: a problem means "no saved chat", never a crash.
const KEY = "moroccotech-chat-v1";

const ROLES = ["user", "bot", "handoff", "error"];

// Saved data may come from an older version of the page or be edited by hand:
// keep only messages the page can draw, so one bad item cannot break it.
function isValidMessage(message) {
  return (
    typeof message?.id === "string" &&
    ROLES.includes(message.role) &&
    typeof message.text === "string" &&
    typeof message.time === "string" &&
    !Number.isNaN(Date.parse(message.time)) &&
    (message.role !== "error" || typeof message.retryText === "string")
  );
}

export function loadChat() {
  try {
    const data = JSON.parse(localStorage.getItem(KEY));
    if (!data || !Array.isArray(data.messages)) return null;
    const messages = data.messages.filter(isValidMessage);
    if (messages.length === 0) return null;
    const sessionId = typeof data.sessionId === "string" ? data.sessionId : null;
    return { sessionId, messages };
  } catch {
    return null;
  }
}

export function saveChat({ sessionId, messages }) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ sessionId, messages }));
  } catch {
    // nothing to do: the chat still works, it just won't survive a reload
  }
}

export function clearChat() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // same as above
  }
}
