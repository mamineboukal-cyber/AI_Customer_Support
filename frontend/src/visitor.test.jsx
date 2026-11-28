// The visitor id on the page: the server creates it, the page stores and resends it.
import { afterEach, describe, expect, test, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import STRINGS from "./strings";

const VISITOR_KEY = "moroccotech-visitor-v1";
const V1 = "11111111-1111-4111-8111-111111111111";
const V2 = "22222222-2222-4222-8222-222222222222";

// fetch replaced by a queue we control: each call waits until the test answers it.
function controlledFetch() {
  const calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (url, options) =>
        new Promise((resolve) => calls.push({ body: JSON.parse(options.body), resolve })),
    ),
  );
  return {
    calls,
    async answer(i, data) {
      const body = { reply: `r${i}`, session_id: `S${i}`, handoff: false, ...data };
      await act(async () => calls[i].resolve(new Response(JSON.stringify(body), { status: 200 })));
    },
  };
}

async function send(text) {
  await userEvent.type(screen.getByRole("textbox", { name: STRINGS.inputLabel }), `${text}{Enter}`);
}

function blockStorage() {
  for (const method of ["getItem", "setItem", "removeItem"]) {
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new Error("storage blocked");
    });
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("visitor id", () => {
  test("the first message has no visitor id: the page never makes one up", async () => {
    const randomUUID = vi.spyOn(crypto, "randomUUID");
    const api = controlledFetch();
    render(<App />);

    await send("one");

    expect(api.calls[0].body).toEqual({ message: "one" });
    expect(randomUUID).not.toHaveBeenCalled();
  });

  test("the id from the server is stored and sent with every next message", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, { visitor_id: V1 });
    await send("two");
    await api.answer(1, { visitor_id: V1 });
    await send("three");

    expect(localStorage.getItem(VISITOR_KEY)).toBe(V1);
    expect(api.calls[1].body).toEqual({ message: "two", session_id: "S0", visitor_id: V1 });
    expect(api.calls[2].body).toEqual({ message: "three", session_id: "S1", visitor_id: V1 });
  });

  test("a stored id is sent after a reload", async () => {
    localStorage.setItem(VISITOR_KEY, V1);
    const api = controlledFetch();
    render(<App />);

    await send("hi");

    expect(api.calls[0].body).toEqual({ message: "hi", visitor_id: V1 });
  });

  test("New chat keeps the visitor id and drops only the session", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, { visitor_id: V1 });
    await userEvent.click(screen.getByRole("button", { name: STRINGS.newChat }));
    await send("fresh");

    expect(api.calls[1].body).toEqual({ message: "fresh", visitor_id: V1 });
    expect(localStorage.getItem(VISITOR_KEY)).toBe(V1);
  });

  test("a reply that arrives after New chat still teaches the page its visitor id", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await userEvent.click(screen.getByRole("button", { name: STRINGS.newChat }));
    await api.answer(0, { visitor_id: V1 });
    await send("fresh");

    expect(screen.queryByText("r0")).toBeNull();
    expect(api.calls[1].body).toEqual({ message: "fresh", visitor_id: V1 });
  });

  test("the server's id replaces the one sent (an unknown id gets a new one)", async () => {
    localStorage.setItem(VISITOR_KEY, V1);
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, { visitor_id: V2 });
    await send("two");

    expect(api.calls[1].body.visitor_id).toBe(V2);
    expect(localStorage.getItem(VISITOR_KEY)).toBe(V2);
  });

  test("a response without a usable visitor id keeps the current one", async () => {
    localStorage.setItem(VISITOR_KEY, V1);
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, { visitor_id: "not-a-uuid" });
    await send("two");
    await api.answer(1, { visitor_id: undefined });
    await send("three");

    expect(api.calls[1].body.visitor_id).toBe(V1);
    expect(api.calls[2].body.visitor_id).toBe(V1);
    expect(localStorage.getItem(VISITOR_KEY)).toBe(V1);
  });

  test.each([["not-a-uuid"], [""], ["{}"], [`${V1} `]])(
    "a damaged stored id (%j) is not sent, so the server does not refuse every message",
    async (stored) => {
      localStorage.setItem(VISITOR_KEY, stored);
      const api = controlledFetch();
      render(<App />);

      await send("hi");

      expect(api.calls[0].body).toEqual({ message: "hi" });
    },
  );

  test("without storage the page works and keeps the id in memory", async () => {
    blockStorage();
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, { visitor_id: V1 });
    expect(screen.getByText("r0")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: STRINGS.newChat }));
    await send("two");

    expect(api.calls[1].body).toEqual({ message: "two", visitor_id: V1 });
  });
});
