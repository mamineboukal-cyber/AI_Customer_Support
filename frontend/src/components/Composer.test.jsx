import { describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Composer from "./Composer";
import STRINGS from "../strings";

function setup(props = {}) {
  const onSend = vi.fn();
  render(<Composer disabled={false} onSend={onSend} {...props} />);
  return { onSend, input: screen.getByRole("textbox", { name: STRINGS.inputLabel }) };
}

describe("Composer", () => {
  test("Enter sends the trimmed text and empties the field", async () => {
    const { onSend, input } = setup();

    await userEvent.type(input, "  hello {Enter}");

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(input).toHaveValue("");
  });

  test("Shift+Enter adds a new line and does not send", async () => {
    const { onSend, input } = setup();

    await userEvent.type(input, "line 1{Shift>}{Enter}{/Shift}line 2");

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("line 1\nline 2");
  });

  test("Enter while an input method is composing does not send", () => {
    const { onSend, input } = setup();
    fireEvent.change(input, { target: { value: "مرحبا" } });

    fireEvent.keyDown(input, { key: "Enter", isComposing: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  test("whitespace only cannot be sent", async () => {
    const { onSend, input } = setup();

    await userEvent.type(input, "   {Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: STRINGS.send })).toBeDisabled();
  });

  test("while disabled, the button is off and Enter does not send, but typing still works", async () => {
    const { onSend, input } = setup({ disabled: true });

    await userEvent.type(input, "hello{Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: STRINGS.send })).toBeDisabled();
    expect(input).toHaveValue("hello");
  });

  test("the send button sends", async () => {
    const { onSend, input } = setup();

    await userEvent.type(input, "hi");
    await userEvent.click(screen.getByRole("button", { name: STRINGS.send }));

    expect(onSend).toHaveBeenCalledWith("hi");
  });

  test("limit is 2000 characters and the counter appears from 1800", () => {
    const { input } = setup();
    expect(input).toHaveAttribute("maxLength", "2000");

    fireEvent.change(input, { target: { value: "x".repeat(1799) } });
    expect(screen.queryByText(STRINGS.counter(1799, 2000))).toBeNull();

    fireEvent.change(input, { target: { value: "x".repeat(1800) } });
    expect(screen.getByText(STRINGS.counter(1800, 2000))).toBeInTheDocument();
  });
});
