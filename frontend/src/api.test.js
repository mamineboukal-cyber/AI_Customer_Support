import { afterEach, describe, expect, test, vi } from "vitest";
import { ChatError, sendMessage } from "./api";

function respond(status, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return Promise.resolve(new Response(text, { status }));
}

function mockFetch(impl) {
  const fetchMock = vi.fn(impl);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("sendMessage", () => {
  test("first message is sent without session_id", async () => {
    const fetchMock = mockFetch(() => respond(200, { reply: "r", session_id: "A", handoff: false }));

    await sendMessage("hi", null);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/chat");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ message: "hi" });
  });

  test("later messages carry the session_id", async () => {
    const fetchMock = mockFetch(() => respond(200, { reply: "r", session_id: "A", handoff: false }));

    await sendMessage("hi", "abc");

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ message: "hi", session_id: "abc" });
  });

  test("the response is mapped to reply, sessionId, handoff", async () => {
    mockFetch(() => respond(200, { reply: "Hello", session_id: "B", handoff: true }));

    expect(await sendMessage("hi", null)).toEqual({ reply: "Hello", sessionId: "B", handoff: true });
  });

  test.each([
    ["a 500 with a text body", () => respond(500, "Internal Server Error")],
    ["a 422", () => respond(422, { detail: [] })],
    ["a body that is not JSON", () => respond(200, "<html>")],
    ["a body without reply", () => respond(200, { session_id: "A" })],
    ["a network error", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("%s throws ChatError", async (_name, impl) => {
    mockFetch(impl);

    await expect(sendMessage("hi", null)).rejects.toBeInstanceOf(ChatError);
  });
});
