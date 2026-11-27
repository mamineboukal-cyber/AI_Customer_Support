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

  test("clearChat removes the saved chat", () => {
    saveChat(chat);
    clearChat();
    expect(loadChat()).toBeNull();
  });
});
