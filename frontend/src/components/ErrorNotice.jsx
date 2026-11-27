import STRINGS from "../strings";

// Shown when the server could not be reached. Never shows technical details.
export default function ErrorNotice({ onRetry }) {
  return (
    <li className="error-notice" role="alert">
      <p>{STRINGS.errorText}</p>
      <button type="button" className="retry-button" onClick={onRetry}>
        {STRINGS.retry}
      </button>
    </li>
  );
}
