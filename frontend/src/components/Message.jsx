import STRINGS from "../strings";

const timeFormat = new Intl.DateTimeFormat(STRINGS.locale, {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

// One chat bubble plus a small "sender · time" line under it.
// The text is a normal React child, so HTML in a reply is shown as text.
// dir="auto" lets the browser pick left-to-right or right-to-left per message.
export default function Message({ message }) {
  const fromUser = message.role === "user";
  const sender = fromUser ? STRINGS.you : STRINGS.botName;

  return (
    <li className={`message ${fromUser ? "message-user" : "message-bot"}`}>
      <p className="bubble" dir="auto">
        {message.text}
      </p>
      <span className="message-meta">
        {sender} · {timeFormat.format(new Date(message.time))}
      </span>
    </li>
  );
}
