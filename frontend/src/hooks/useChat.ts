import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import { postChatMessage } from "../api/chat";
import type { ChatMessage } from "../types/chat";

const RATE_LIMIT_COOLDOWN_SECONDS = 30;

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isRateLimited, setIsRateLimited] = useState(false);
  const [rateLimitCooldownSeconds, setRateLimitCooldownSeconds] = useState(0);
  const lastUserMessageText = useRef<string | null>(null);
  const cooldownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const mutation = useMutation({ mutationFn: postChatMessage });

  useEffect(
    () => () => {
      if (cooldownIntervalRef.current) clearInterval(cooldownIntervalRef.current);
    },
    [],
  );

  const startRateLimitCooldown = useCallback(() => {
    setIsRateLimited(true);
    setRateLimitCooldownSeconds(RATE_LIMIT_COOLDOWN_SECONDS);
    if (cooldownIntervalRef.current) clearInterval(cooldownIntervalRef.current);
    cooldownIntervalRef.current = setInterval(() => {
      setRateLimitCooldownSeconds((seconds) => {
        if (seconds <= 1) {
          if (cooldownIntervalRef.current) clearInterval(cooldownIntervalRef.current);
          setIsRateLimited(false);
          return 0;
        }
        return seconds - 1;
      });
    }, 1000);
  }, []);

  const performSend = useCallback(
    (text: string) => {
      setError(null);
      mutation.mutate(text, {
        onSuccess: (data) => {
          setMessages((previous) => [
            ...previous,
            {
              role: "assistant",
              content: data.assistant_message,
              awaitingClarification: data.awaiting_clarification,
            },
          ]);
        },
        onError: (mutationError) => {
          if (axios.isAxiosError(mutationError)) {
            const status = mutationError.response?.status;
            if (status === 429) {
              startRateLimitCooldown();
              return;
            }
            if (status === 401) {
              setError("Configuration error. Please contact support.");
              console.error("Chat widget configuration error (401):", mutationError);
              return;
            }
          }
          setError("Something went wrong. Please try again.");
          console.error("Chat request failed:", mutationError);
        },
      });
    },
    [mutation, startRateLimitCooldown],
  );

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      lastUserMessageText.current = trimmed;
      setMessages((previous) => [...previous, { role: "user", content: trimmed }]);
      performSend(trimmed);
    },
    [performSend],
  );

  const retryLastMessage = useCallback(() => {
    if (lastUserMessageText.current) {
      performSend(lastUserMessageText.current);
    }
  }, [performSend]);

  return {
    messages,
    sendMessage,
    isLoading: mutation.isPending,
    isRateLimited,
    rateLimitCooldownSeconds,
    error,
    retryLastMessage,
  };
}
