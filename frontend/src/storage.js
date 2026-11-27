// Saves the conversation in the browser so a reload restores it.
// localStorage can be full, blocked (private mode) or hold old data, so
// every access is wrapped: a problem means "no saved chat", never a crash.
const KEY = "moroccotech-chat-v1";

export function loadChat() {
  try {
    const data = JSON.parse(localStorage.getItem(KEY));
    if (!data || !Array.isArray(data.messages)) return null;
    return { sessionId: data.sessionId ?? null, messages: data.messages };
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
