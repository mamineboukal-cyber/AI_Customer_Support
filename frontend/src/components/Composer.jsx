import { useRef, useState } from "react";
import STRINGS from "../strings";

export const MAX_LENGTH = 2000; // same limit as the server
const COUNTER_FROM = 1800;

// The message box at the bottom of the chat. It keeps its own text, grows
// with the text (up to a few lines, see CSS), and calls onSend with the
// trimmed text. Enter sends, Shift+Enter makes a new line.
export default function Composer({ disabled, onSend }) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);
  const canSend = !disabled && text.trim() !== "";

  function resize() {
    const input = inputRef.current;
    if (!input) return; // the component may be gone by the next animation frame
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }

  function submit() {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
    requestAnimationFrame(resize);
  }

  function handleKeyDown(event) {
    // isComposing: the user is still building a character with an input
    // method (some Arabic keyboards). Enter then confirms it, it must not send.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={inputRef}
        className="composer-input"
        rows={1}
        dir="auto"
        maxLength={MAX_LENGTH}
        value={text}
        placeholder={STRINGS.inputPlaceholder}
        aria-label={STRINGS.inputLabel}
        onChange={(event) => {
          setText(event.target.value);
          resize();
        }}
        onKeyDown={handleKeyDown}
      />
      {text.length >= COUNTER_FROM && (
        <span className="composer-counter">{STRINGS.counter(text.length, MAX_LENGTH)}</span>
      )}
      <button type="submit" className="send-button" disabled={!canSend} aria-label={STRINGS.send}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      </button>
    </form>
  );
}
