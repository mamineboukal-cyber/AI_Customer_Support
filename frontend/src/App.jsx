import STRINGS from "./strings";
import useChat from "./useChat";
import ChatCard from "./components/ChatCard";
import BotCard from "./components/BotCard";
import QuickQuestions from "./components/QuickQuestions";
import StoreFacts from "./components/StoreFacts";
import "./styles/tokens.css";
import "./styles/app.css";

// The page: four bento cards. The chat comes first in the HTML, so on a phone
// (one column) it is the first thing you see.
export default function App() {
  const chat = useChat();

  return (
    <div className="page" dir={STRINGS.dir} lang={STRINGS.locale}>
      <main className="bento">
        <ChatCard
          messages={chat.messages}
          waiting={chat.waiting}
          onSend={chat.send}
          onRetry={chat.retry}
          onNewChat={chat.newChat}
        />
        <BotCard />
        <QuickQuestions disabled={chat.waiting} onAsk={chat.send} />
        <StoreFacts />
      </main>
    </div>
  );
}
