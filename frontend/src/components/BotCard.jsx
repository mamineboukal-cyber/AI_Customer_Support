import STRINGS from "../strings";
import BotIcon from "./BotIcon";

// Small card that introduces the bot. Its name comes from strings.js.
export default function BotCard() {
  return (
    <section className="card card-bot">
      <BotIcon size={72} />
      <h2>{STRINGS.botName}</h2>
      <p>{STRINGS.botTagline}</p>
    </section>
  );
}
