// Original robot icon drawn as SVG, so it stays sharp at any size.
// Colors come from CSS classes (see app.css), not from this file.
export default function BotIcon({ size = 40 }) {
  return (
    <svg className="bot-icon" width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle className="bot-icon-bg" cx="32" cy="32" r="32" />
      <line className="bot-icon-line" x1="32" y1="10" x2="32" y2="18" />
      <circle className="bot-icon-accent" cx="32" cy="9" r="3.5" />
      <rect className="bot-icon-head" x="14" y="18" width="36" height="30" rx="12" />
      <rect className="bot-icon-face" x="19" y="23" width="26" height="18" rx="8" />
      <circle className="bot-icon-eye" cx="26" cy="31" r="3" />
      <circle className="bot-icon-eye" cx="38" cy="31" r="3" />
      <path className="bot-icon-smile" d="M27 36.5 q5 3.5 10 0" />
      <rect className="bot-icon-head" x="10" y="28" width="4" height="10" rx="2" />
      <rect className="bot-icon-head" x="50" y="28" width="4" height="10" rx="2" />
    </svg>
  );
}
