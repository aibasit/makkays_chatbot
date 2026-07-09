import ChatWindow from "../components/ChatWindow";
import MessageInput from "../components/MessageInput";
import RateLimitNotice from "../components/RateLimitNotice";
import { useChat } from "../hooks/useChat";

export default function ChatPage() {
  const {
    messages,
    sendMessage,
    isLoading,
    isRateLimited,
    rateLimitCooldownSeconds,
    error,
    retryLastMessage,
  } = useChat();

  return (
    <div className="flex min-h-screen items-center justify-center p-0 sm:p-6">
      <div className="flex h-screen w-full flex-col overflow-hidden bg-white shadow-none sm:h-[85vh] sm:max-w-2xl sm:rounded-2xl sm:shadow-xl sm:ring-1 sm:ring-slate-200">
        <header className="flex items-center gap-3 border-b border-slate-100 bg-white px-5 py-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-600 text-base font-semibold text-white">
            M
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-slate-900">Makkays AI Sales Engineer</h1>
            <p className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              Online now
            </p>
          </div>
        </header>

        <ChatWindow messages={messages} error={error} isLoading={isLoading} onRetry={retryLastMessage} onSendMessage={sendMessage} />

        {isRateLimited && <RateLimitNotice cooldownSeconds={rateLimitCooldownSeconds} />}
        <MessageInput onSend={sendMessage} isLoading={isLoading || isRateLimited} />
      </div>
    </div>
  );
}
