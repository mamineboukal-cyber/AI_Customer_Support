import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import TypingIndicator from "./TypingIndicator";
import STRINGS from "../strings";

test("shows three dots and the word Typing in a live status", () => {
  const { container } = render(<TypingIndicator />);

  expect(screen.getByRole("status")).toHaveTextContent(STRINGS.typing);
  expect(container.querySelectorAll(".typing-dot")).toHaveLength(3);
});
