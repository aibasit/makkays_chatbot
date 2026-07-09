import { useEffect, useRef } from "react";

import type { ChatMessage } from "../types/chat";
import ClarificationOptions from "./ClarificationOptions";
import MessageBubble, { ErrorBubble, TypingBubble } from "./MessageBubble";

type ChatWindowProps = {
  messages: ChatMessage[];
  error: string | null;
  isLoading: boolean;
  onRetry: () => void;
  onSendMessage: (text: string) => void;
};

export default function ChatWindow({ messages, error, isLoading, onRetry, onSendMessage }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error, isLoading]);

  return (
    <div className="scrollbar-thin flex flex-1 flex-col gap-3 overflow-y-auto bg-slate-50/40 p-4">
      {messages.length === 0 && !isLoading && (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center text-slate-400">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-xl">💬</div>
          <p className="text-sm font-medium text-slate-500">How can I help you today?</p>
          <p className="max-w-xs text-xs text-slate-400">
            Ask about products, pricing, availability, or technical support.
          </p>
        </div>
      )}
      {messages.map((message, index) =>
        message.role === "assistant" && message.awaitingClarification ? (
          <ClarificationOptions key={index} message={message.content} onSelect={onSendMessage} />
        ) : (
          <MessageBubble key={index} message={message} />
        ),
      )}
      {isLoading && <TypingBubble />}
      {error && <ErrorBubble message={error} onRetry={onRetry} />}
      <div ref={bottomRef} />
    </div>
  );
}
