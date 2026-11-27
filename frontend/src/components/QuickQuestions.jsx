import STRINGS from "../strings";

// Ready-made questions: clicking one sends it like a typed message.
export default function QuickQuestions({ disabled, onAsk }) {
  return (
    <section className="card card-quick">
      <h2>{STRINGS.quickTitle}</h2>
      <ul className="quick-list">
        {STRINGS.quickQuestions.map((question) => (
          <li key={question}>
            <button type="button" className="quick-button" disabled={disabled} onClick={() => onAsk(question)}>
              {question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
