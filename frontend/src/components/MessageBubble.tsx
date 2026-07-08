import type { ChatMessage } from "../types/chat";

type MessageBubbleProps = {
  message: ChatMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        data-testid="message-bubble"
        data-role={message.role}
        className={`max-w-[75%] rounded-lg px-4 py-2 text-sm ${
          isUser ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-900"
        }`}
      >
        {message.content}
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
    <div className="flex justify-start">
      <div data-testid="error-bubble" className="max-w-[75%] rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">
        <p>{message}</p>
        <button type="button" onClick={onRetry} className="mt-1 text-xs font-semibold text-red-800 underline">
          Retry
        </button>
      </div>
    </div>
  );
}

export default MessageBubble;
