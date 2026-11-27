import { useEffect, useRef } from "react";
import Message from "./Message";
import HandoffNotice from "./HandoffNotice";
import ErrorNotice from "./ErrorNotice";
import TypingIndicator from "./TypingIndicator";

// The scrolling list of everything in the chat. Each item's `role` decides
// how it is drawn. It scrolls to the newest item whenever something changes.
export default function MessageList({ messages, waiting, onRetry }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, waiting]);

  return (
    <div className="message-scroll">
      <ol className="message-list" role="log" aria-live="polite">
        {messages.map((message) => {
          if (message.role === "handoff") return <HandoffNotice key={message.id} />;
          if (message.role === "error")
            return <ErrorNotice key={message.id} onRetry={() => onRetry(message.id)} />;
          return <Message key={message.id} message={message} />;
        })}
      </ol>
      {waiting && <TypingIndicator />}
      <div ref={endRef} />
    </div>
  );
}
