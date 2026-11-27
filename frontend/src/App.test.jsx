import { afterEach, describe, expect, test, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import useChat from "./useChat";
import STRINGS from "./strings";

// fetch replaced by a queue we control: each call waits until the test answers it.
function controlledFetch() {
  const calls = [];
  const fetchMock = vi.fn(
    (url, options) =>
      new Promise((resolve, reject) => {
        calls.push({ body: JSON.parse(options.body), resolve, reject });
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const ok = (data) => new Response(JSON.stringify(data), { status: 200 });
  return {
    fetchMock,
    calls,
    async answer(i, reply, sessionId, handoff = false) {
      await act(async () => calls[i].resolve(ok({ reply, session_id: sessionId, handoff })));
    },
    async fail(i) {
      await act(async () => calls[i].reject(new TypeError("Failed to fetch")));
    },
  };
}

async function send(text) {
  await userEvent.type(screen.getByRole("textbox", { name: STRINGS.inputLabel }), `${text}{Enter}`);
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  test("first load shows the greeting", () => {
    render(<App />);

    expect(screen.getByText(STRINGS.greeting)).toBeInTheDocument();
  });

  test("a message shows Typing while waiting, then the reply", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("hi");
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(STRINGS.typing);

    await api.answer(0, "Hello from Zelli", "A");
    expect(screen.getByText("Hello from Zelli")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  test("always sends the session_id of the last response, also after a reload", async () => {
    const api = controlledFetch();
    const { unmount } = render(<App />);

    await send("one");
    await api.answer(0, "r1", "A");
    await send("two");
    await api.answer(1, "r2", "B");
    unmount();

    render(<App />);
    expect(screen.getByText("r1")).toBeInTheDocument();
    expect(screen.getByText("r2")).toBeInTheDocument();
    await send("three");

    expect(api.calls[0].body).toEqual({ message: "one" });
    expect(api.calls[1].body).toEqual({ message: "two", session_id: "A" });
    expect(api.calls[2].body).toEqual({ message: "three", session_id: "B" });
  });

  test("an error shows Retry, and Retry resends without repeating the message", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("hi");
    await api.fail(0);
    expect(screen.getByText(STRINGS.errorText)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: STRINGS.retry }));
    await api.answer(1, "Back online", "A");

    expect(screen.getByText("Back online")).toBeInTheDocument();
    expect(screen.queryByText(STRINGS.errorText)).toBeNull();
    expect(screen.getAllByText("hi")).toHaveLength(1);
    expect(api.fetchMock).toHaveBeenCalledTimes(2);
    expect(api.calls[1].body).toEqual({ message: "hi" });
  });

  test("handoff shows the reply, the system line and the card", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("Can you fix my TV?");
    await api.answer(0, "I don't know. Let me connect you to a human agent.", "A", true);

    expect(screen.getByText("I don't know. Let me connect you to a human agent.")).toBeInTheDocument();
    expect(screen.getByText(STRINGS.handoffLine)).toBeInTheDocument();
    expect(screen.getByText(STRINGS.handoffTitle)).toBeInTheDocument();
  });

  test("a quick question is sent when clicked, and the buttons are off while waiting", async () => {
    const api = controlledFetch();
    render(<App />);
    const question = STRINGS.quickQuestions[0];

    await userEvent.click(screen.getByRole("button", { name: question }));

    expect(api.calls[0].body).toEqual({ message: question });
    expect(screen.getByRole("button", { name: question })).toBeDisabled();
  });

  test("New chat while waiting: the late reply is dropped and the next message has no session", async () => {
    const api = controlledFetch();
    render(<App />);

    await send("one");
    await api.answer(0, "r1", "A");
    await send("two");
    await userEvent.click(screen.getByRole("button", { name: STRINGS.newChat }));
    await api.answer(1, "late reply", "A");

    expect(screen.queryByText("late reply")).toBeNull();
    expect(screen.queryByText("one")).toBeNull();
    expect(screen.getByText(STRINGS.greeting)).toBeInTheDocument();

    await send("fresh");
    expect(api.calls[2].body).toEqual({ message: "fresh" });
  });

  test("corrupt saved data still shows the greeting", () => {
    localStorage.setItem("moroccotech-chat-v1", "{oops");

    render(<App />);

    expect(screen.getByText(STRINGS.greeting)).toBeInTheDocument();
  });
});

describe("useChat", () => {
  test("two sends in the same moment make only one request", async () => {
    const api = controlledFetch();
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.send("a");
      result.current.send("b");
    });

    await waitFor(() => expect(api.fetchMock).toHaveBeenCalledTimes(1));
    expect(result.current.messages.filter((m) => m.role === "user")).toHaveLength(1);
  });
});
