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
    <form onSubmit={handleSubmit} className="flex flex-col gap-1 border-t border-gray-200 p-3">
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value.slice(0, maxLength))}
          disabled={isLoading}
          placeholder="Type your message..."
          aria-label="Message"
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-100"
        />
        <button
          type="submit"
          disabled={isLoading || isEmpty}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-gray-300"
        >
          Send
        </button>
      </div>
      {showCounter && (
        <span className="text-right text-xs text-gray-500">
          {value.length}/{maxLength}
        </span>
      )}
    </form>
  );
}
