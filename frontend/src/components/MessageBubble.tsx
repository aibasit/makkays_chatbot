import type { ChatMessage } from "../types/chat";

type MessageBubbleProps = {
  message: ChatMessage;
};

function BotAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
      M
    </div>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  return (
    <div className={`flex animate-message-in items-end gap-2 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <BotAvatar />}
      <div
        data-testid="message-bubble"
        data-role={message.role}
        className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
          isUser
            ? "rounded-br-sm bg-blue-600 text-white"
            : "rounded-bl-sm border border-slate-100 bg-white text-slate-800"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}

export function TypingBubble() {
  return (
    <div className="flex animate-message-in items-end gap-2">
      <BotAvatar />
      <div
        data-testid="typing-bubble"
        className="flex items-center gap-1 rounded-2xl rounded-bl-sm border border-slate-100 bg-white px-4 py-3 shadow-sm"
      >
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-slate-400" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-slate-400" />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-slate-400" />
      </div>
    </div>
  );
}

type ErrorBubbleProps = {
  message: string;
  onRetry: () => void;
};

export function ErrorBubble({ message, onRetry }: ErrorBubbleProps) {
  return (
    <div className="flex animate-message-in justify-start">
      <div
        data-testid="error-bubble"
        className="max-w-[75%] rounded-2xl rounded-bl-sm border border-red-100 bg-red-50 px-4 py-2.5 text-sm text-red-700 shadow-sm"
      >
        <p>{message}</p>
        <button type="button" onClick={onRetry} className="mt-1 text-xs font-semibold text-red-800 underline">
          Retry
        </button>
      </div>
    </div>
  );
}

export default MessageBubble;
