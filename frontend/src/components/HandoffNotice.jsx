import STRINGS from "../strings";

// Shown under a reply when the bot could not answer. It tells the truth:
// no human is in this chat, and no reply time is promised.
export default function HandoffNotice() {
  return (
    <li className="handoff">
      <p className="system-line">{STRINGS.handoffLine}</p>
      <div className="handoff-card">
        <p className="handoff-title">{STRINGS.handoffTitle}</p>
        <p>{STRINGS.handoffBody}</p>
      </div>
    </li>
  );
}
