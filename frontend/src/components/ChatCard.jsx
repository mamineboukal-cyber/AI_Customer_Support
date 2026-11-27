import STRINGS from "../strings";
import BotIcon from "./BotIcon";
import MessageList from "./MessageList";
import Composer from "./Composer";

// The big card: a header (icon, title, "New chat"), the messages, the input.
export default function ChatCard({ messages, waiting, onSend, onRetry, onNewChat }) {
  return (
    <section className="card card-chat" aria-label={STRINGS.title}>
      <header className="chat-header">
        <BotIcon size={40} />
        <div className="chat-header-text">
          <h1>{STRINGS.title}</h1>
          <p>{STRINGS.botName}</p>
        </div>
        <button type="button" className="new-chat-button" onClick={onNewChat}>
          {STRINGS.newChat}
        </button>
      </header>
      <MessageList messages={messages} waiting={waiting} onRetry={onRetry} />
      <Composer disabled={waiting} onSend={onSend} />
    </section>
  );
}
