import STRINGS from "../strings";

// A few store facts taken from the knowledge base, shown as small tiles.
export default function StoreFacts() {
  return (
    <section className="card card-facts">
      <h2>{STRINGS.factsTitle}</h2>
      <ul className="facts-grid">
        {STRINGS.facts.map((fact) => (
          <li key={fact.value} className="fact">
            <p className="fact-label">{fact.label}</p>
            <p className="fact-value">{fact.value}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
