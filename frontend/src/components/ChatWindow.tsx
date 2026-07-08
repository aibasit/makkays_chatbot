import { useEffect, useRef } from "react";

import type { ChatMessage } from "../types/chat";
import ClarificationOptions from "./ClarificationOptions";
import MessageBubble, { ErrorBubble } from "./MessageBubble";

type ChatWindowProps = {
  messages: ChatMessage[];
  error: string | null;
  onRetry: () => void;
  onSendMessage: (text: string) => void;
};

export default function ChatWindow({ messages, error, onRetry, onSendMessage }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error]);

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      {messages.map((message, index) =>
        message.role === "assistant" && message.awaitingClarification ? (
          <ClarificationOptions key={index} message={message.content} onSelect={onSendMessage} />
        ) : (
          <MessageBubble key={index} message={message} />
        ),
      )}
      {error && <ErrorBubble message={error} onRetry={onRetry} />}
      <div ref={bottomRef} />
    </div>
  );
}
