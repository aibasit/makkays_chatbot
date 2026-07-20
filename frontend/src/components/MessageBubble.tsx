import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessage } from "../types/chat";

type MessageBubbleProps = {
  message: ChatMessage;
};

function BotAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
      IS
    </div>
  );
}

const markdownComponents = {
  p: (props: ComponentPropsWithoutRef<"p">) => <p className="mb-2 last:mb-0" {...props} />,
  h1: (props: ComponentPropsWithoutRef<"h1">) => (
    <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0" {...props} />
  ),
  h2: (props: ComponentPropsWithoutRef<"h2">) => (
    <h2 className="mb-2 mt-3 text-[0.95rem] font-semibold first:mt-0" {...props} />
  ),
  h3: (props: ComponentPropsWithoutRef<"h3">) => (
    <h3 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0" {...props} />
  ),
  ul: (props: ComponentPropsWithoutRef<"ul">) => (
    <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0" {...props} />
  ),
  ol: (props: ComponentPropsWithoutRef<"ol">) => (
    <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0" {...props} />
  ),
  li: (props: ComponentPropsWithoutRef<"li">) => <li className="pl-0.5" {...props} />,
  strong: (props: ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-semibold text-slate-900" {...props} />
  ),
  a: (props: ComponentPropsWithoutRef<"a">) => (
    <a className="text-blue-600 underline hover:text-blue-700" target="_blank" rel="noreferrer" {...props} />
  ),
  code: (props: ComponentPropsWithoutRef<"code">) => (
    <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]" {...props} />
  ),
  table: (props: ComponentPropsWithoutRef<"table">) => (
    <div className="mb-2 -mx-1 overflow-x-auto last:mb-0">
      <table className="min-w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  thead: (props: ComponentPropsWithoutRef<"thead">) => <thead className="bg-slate-50" {...props} />,
  th: (props: ComponentPropsWithoutRef<"th">) => (
    <th className="border border-slate-200 px-2 py-1.5 font-semibold text-slate-700" {...props} />
  ),
  td: (props: ComponentPropsWithoutRef<"td">) => (
    <td className="border border-slate-200 px-2 py-1.5 align-top" {...props} />
  ),
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  return (
    <div className={`flex animate-message-in items-end gap-2 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <BotAvatar />}
      <div
        data-testid="message-bubble"
        data-role={message.role}
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
          isUser
            ? "whitespace-pre-wrap rounded-br-sm bg-blue-600 text-white"
            : "rounded-bl-sm border border-slate-100 bg-white text-slate-800"
        }`}
      >
        {isUser ? (
          message.content
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {message.content}
          </ReactMarkdown>
        )}
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
