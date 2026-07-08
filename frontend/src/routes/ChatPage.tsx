import ChatWindow from "../components/ChatWindow";
import MessageInput from "../components/MessageInput";
import RateLimitNotice from "../components/RateLimitNotice";
import { useChat } from "../hooks/useChat";

export default function ChatPage() {
  const { messages, sendMessage, isLoading, isRateLimited, rateLimitCooldownSeconds, error, retryLastMessage } =
    useChat();

  return (
    <div className="mx-auto flex h-screen max-w-2xl flex-col bg-white">
      <header className="border-b border-gray-200 p-4">
        <h1 className="text-lg font-semibold text-gray-900">Makkays AI Sales Engineer</h1>
      </header>
      <ChatWindow messages={messages} error={error} onRetry={retryLastMessage} onSendMessage={sendMessage} />
      {isRateLimited && <RateLimitNotice cooldownSeconds={rateLimitCooldownSeconds} />}
      <MessageInput onSend={sendMessage} isLoading={isLoading || isRateLimited} />
    </div>
  );
}
