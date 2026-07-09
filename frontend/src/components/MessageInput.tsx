import { useState, type FormEvent } from "react";

const DEFAULT_MAX_LENGTH = 4000;
const COUNTER_THRESHOLD_RATIO = 0.8;

type MessageInputProps = {
  onSend: (text: string) => void;
  isLoading: boolean;
  maxLength?: number;
};

export default function MessageInput({ onSend, isLoading, maxLength = DEFAULT_MAX_LENGTH }: MessageInputProps) {
  const [value, setValue] = useState("");
  const isEmpty = value.trim().length === 0;
  const showCounter = value.length >= maxLength * COUNTER_THRESHOLD_RATIO;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (isEmpty || isLoading) return;
    onSend(value);
    setValue("");
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-1 border-t border-slate-100 bg-white p-3">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value.slice(0, maxLength))}
          disabled={isLoading}
          placeholder="Type your message..."
          aria-label="Message"
          className="flex-1 rounded-full border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100 disabled:text-slate-400"
        />
        <button
          type="submit"
          disabled={isLoading || isEmpty}
          aria-label="Send"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400"
        >
          <svg viewBox="0 0 24 24" fill="none" className="h-4.5 w-4.5 translate-x-[-1px]" aria-hidden="true">
            <path
              d="M4 12h15m0 0-6-6m6 6-6 6"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
      {showCounter && (
        <span className="pr-1 text-right text-xs text-slate-400">
          {value.length}/{maxLength}
        </span>
      )}
    </form>
  );
}
