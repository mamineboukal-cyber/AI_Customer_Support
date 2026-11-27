import { useEffect, useRef, useState } from "react";
import STRINGS from "./strings";
import { sendMessage } from "./api";
import { clearChat, loadChat, saveChat } from "./storage";

// Not crypto.randomUUID(): browsers only offer it on https or localhost,
// and the page may be opened from a phone on the local network over http.
let counter = 0;
function newId() {
  counter += 1;
  return `${Date.now()}-${counter}`;
}

function makeMessage(role, text, extra = {}) {
  return { id: newId(), role, text, time: new Date().toISOString(), ...extra };
}

function freshChat() {
  return { sessionId: null, messages: [makeMessage("bot", STRINGS.greeting)] };
}

// The saved chat, or a new one. If the page was closed while waiting (the last
// item is the customer's question), add an error item so they can press Retry.
function restoreChat() {
  const saved = loadChat();
  if (!saved) return freshChat();
  const last = saved.messages[saved.messages.length - 1];
  if (last.role !== "user") return saved;
  return { ...saved, messages: [...saved.messages, makeMessage("error", "", { retryText: last.text })] };
}

// All the chat logic in one place; the components only display what it returns.
// - messages: everything shown in the chat (user, bot, handoff and error items)
// - waiting: true while a reply is on its way
// - send(text), retry(errorId), newChat()
export default function useChat() {
  const [chat, setChat] = useState(restoreChat);
  const [waiting, setWaiting] = useState(false);
  // Refs change immediately (state only changes on the next render), so they
  // can stop a second send in the same moment and spot replies from an old chat.
  const busy = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    saveChat(chat);
  }, [chat]);

  function addMessages(...items) {
    setChat((current) => ({ ...current, messages: [...current.messages, ...items] }));
  }

  async function ask(text) {
    busy.current = true;
    setWaiting(true);
    const myGeneration = generation.current;
    try {
      const result = await sendMessage(text, chat.sessionId);
      if (myGeneration !== generation.current) return; // "New chat" was pressed meanwhile
      // Always keep the id from the LAST response: the server replaces ids it does not know.
      setChat((current) => ({
        sessionId: result.sessionId,
        messages: [
          ...current.messages,
          makeMessage("bot", result.reply),
          ...(result.handoff ? [makeMessage("handoff", "")] : []),
        ],
      }));
    } catch {
      if (myGeneration !== generation.current) return;
      addMessages(makeMessage("error", "", { retryText: text }));
    } finally {
      if (myGeneration === generation.current) {
        busy.current = false;
        setWaiting(false);
      }
    }
  }

  function send(text) {
    if (busy.current) return;
    addMessages(makeMessage("user", text));
    ask(text);
  }

  function retry(errorId) {
    const failed = chat.messages.find((message) => message.id === errorId);
    if (busy.current || !failed) return;
    setChat((current) => ({
      ...current,
      messages: current.messages.filter((message) => message.id !== errorId),
    }));
    ask(failed.retryText);
  }

  function newChat() {
    generation.current += 1;
    busy.current = false;
    setWaiting(false);
    clearChat();
    setChat(freshChat());
  }

  return { messages: chat.messages, waiting, send, retry, newChat };
}
