import { describe, expect, test, vi, afterEach } from "vitest";
import { clearChat, loadChat, saveChat } from "./storage";

const KEY = "moroccotech-chat-v1";
const chat = {
  sessionId: "abc",
  messages: [{ id: "1", role: "bot", text: "Hi", time: "2026-11-27T10:00:00.000Z" }],
};

afterEach(() => vi.restoreAllMocks());

describe("storage", () => {
  test("save then load gives the same chat back", () => {
    saveChat(chat);
    expect(loadChat()).toEqual(chat);
  });

  test("nothing saved gives null", () => {
    expect(loadChat()).toBeNull();
  });

  test("corrupt JSON gives null", () => {
    localStorage.setItem(KEY, "{not json");
    expect(loadChat()).toBeNull();
  });

  test("wrong shape gives null", () => {
    localStorage.setItem(KEY, JSON.stringify({ messages: "x" }));
    expect(loadChat()).toBeNull();
  });

  test("a storage that throws does not crash save or load", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveChat(chat)).not.toThrow();
    expect(loadChat()).toBeNull();
  });

  test("broken messages are dropped and the good ones kept", () => {
    const good = chat.messages[0];
    localStorage.setItem(
      KEY,
      JSON.stringify({
        sessionId: "abc",
        messages: [
          null,
          { id: "2", role: "bot", text: "no time" },
          { id: "3", role: "bot", text: "bad time", time: "yesterday" },
          { id: "4", role: "robot", text: "unknown role", time: good.time },
          { id: "5", role: "error", text: "", time: good.time },
          good,
        ],
      }),
    );

    expect(loadChat()).toEqual({ sessionId: "abc", messages: [good] });
  });

  test("no valid message left gives null", () => {
    localStorage.setItem(KEY, JSON.stringify({ sessionId: "abc", messages: [] }));
    expect(loadChat()).toBeNull();

    localStorage.setItem(KEY, JSON.stringify({ sessionId: "abc", messages: [{ id: "1" }] }));
    expect(loadChat()).toBeNull();
  });

  test("a session id that is not a string is forgotten", () => {
    localStorage.setItem(KEY, JSON.stringify({ sessionId: 42, messages: chat.messages }));

    expect(loadChat()).toEqual({ sessionId: null, messages: chat.messages });
  });

  test("clearChat removes the saved chat", () => {
    saveChat(chat);
    clearChat();
    expect(loadChat()).toBeNull();
  });
});
