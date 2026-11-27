import { describe, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MessageList from "./MessageList";
import STRINGS from "../strings";

const time = "2026-11-27T10:05:00.000Z";

describe("MessageList", () => {
  test("shows customer and bot messages with sender and time", () => {
    render(
      <MessageList
        messages={[
          { id: "1", role: "user", text: "Hi", time },
          { id: "2", role: "bot", text: "Hello", time },
        ]}
        waiting={false}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByText("Hi")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText(`${STRINGS.you} · 10:05`, { exact: false })).toBeInTheDocument();
    expect(screen.getByText(`${STRINGS.botName} · 10:05`, { exact: false })).toBeInTheDocument();
  });

  test("bot text is shown as plain text, never as HTML", () => {
    const { container } = render(
      <MessageList
        messages={[{ id: "1", role: "bot", text: "<b>bold</b>", time }]}
        waiting={false}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByText("<b>bold</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });

  test("message text has dir=auto so Arabic shows right to left", () => {
    render(
      <MessageList
        messages={[{ id: "1", role: "user", text: "واش كاين K1؟", time }]}
        waiting={false}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByText("واش كاين K1؟")).toHaveAttribute("dir", "auto");
  });

  test("a handoff item shows the system line and the card", () => {
    render(
      <MessageList messages={[{ id: "1", role: "handoff", text: "", time }]} waiting={false} onRetry={() => {}} />,
    );

    expect(screen.getByText(STRINGS.handoffLine)).toBeInTheDocument();
    expect(screen.getByText(STRINGS.handoffTitle)).toBeInTheDocument();
    expect(screen.getByText(STRINGS.handoffBody)).toBeInTheDocument();
  });

  test("an error item shows a friendly text and Retry calls onRetry with its id", async () => {
    const onRetry = vi.fn();
    render(
      <MessageList
        messages={[{ id: "e1", role: "error", text: "", retryText: "hi", time }]}
        waiting={false}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText(STRINGS.errorText)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: STRINGS.retry }));
    expect(onRetry).toHaveBeenCalledWith("e1");
  });

  test("no typing indicator when not waiting", () => {
    render(<MessageList messages={[]} waiting={false} onRetry={() => {}} />);

    expect(screen.queryByRole("status")).toBeNull();
  });

  test("typing indicator while waiting", () => {
    render(<MessageList messages={[]} waiting={true} onRetry={() => {}} />);

    expect(screen.getByRole("status")).toHaveTextContent(STRINGS.typing);
  });
});
