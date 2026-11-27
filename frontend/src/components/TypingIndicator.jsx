import STRINGS from "../strings";

// Three bouncing dots and the word "Typing" while we wait for the reply.
// role="status" makes screen readers announce it without stealing focus.
export default function TypingIndicator() {
  return (
    <div className="typing" role="status">
      <span className="typing-dots" aria-hidden="true">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </span>
      <span>{STRINGS.typing}</span>
    </div>
  );
}
