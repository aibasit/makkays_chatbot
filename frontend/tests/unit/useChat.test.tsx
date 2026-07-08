import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import axios from "axios";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as chatApi from "../../src/api/chat";
import { useChat } from "../../src/hooks/useChat";
import type { ChatResponse } from "../../src/types/chat";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function makeAxiosError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true,
    response: { status },
  });
}

describe("useChat", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("test_useChat_appends_user_message_optimistically_before_response", async () => {
    let resolvePending!: (value: ChatResponse) => void;
    const pending = new Promise<ChatResponse>((resolve) => {
      resolvePending = resolve;
    });
    vi.spyOn(chatApi, "postChatMessage").mockReturnValue(pending);

    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => {
      result.current.sendMessage("Hello");
    });

    expect(result.current.messages).toEqual([{ role: "user", content: "Hello" }]);
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      resolvePending({
        assistant_message: "Hi there",
        session_id: "s1",
        intent: "sales_inquiry",
        awaiting_clarification: false,
      });
      await pending;
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({ role: "assistant", content: "Hi there" });
  });

  it("test_useChat_keeps_optimistic_message_on_error", async () => {
    vi.spyOn(chatApi, "postChatMessage").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      result.current.sendMessage("Hello");
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.messages).toEqual([{ role: "user", content: "Hello" }]);
  });

  it("test_useChat_sets_error_string_on_network_failure", async () => {
    vi.spyOn(chatApi, "postChatMessage").mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      result.current.sendMessage("Hello");
    });

    await waitFor(() => expect(result.current.error).toBe("Something went wrong. Please try again."));
  });

  it("test_useChat_sets_is_rate_limited_on_429", async () => {
    vi.spyOn(chatApi, "postChatMessage").mockRejectedValue(makeAxiosError(429));
    vi.spyOn(axios, "isAxiosError").mockReturnValue(true);

    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      result.current.sendMessage("Hello");
    });

    await waitFor(() => expect(result.current.isRateLimited).toBe(true));
    expect(result.current.rateLimitCooldownSeconds).toBe(30);
    expect(result.current.error).toBeNull();
  });

  it("test_useChat_cooldown_timer_resets_is_rate_limited", async () => {
    vi.spyOn(chatApi, "postChatMessage").mockRejectedValue(makeAxiosError(429));
    vi.spyOn(axios, "isAxiosError").mockReturnValue(true);
    vi.useFakeTimers();

    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      result.current.sendMessage("Hello");
    });
    expect(result.current.isRateLimited).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    expect(result.current.isRateLimited).toBe(false);
    expect(result.current.rateLimitCooldownSeconds).toBe(0);
  });

  it("test_useChat_retry_last_message_resends_last_text", async () => {
    const spy = vi.spyOn(chatApi, "postChatMessage");
    spy.mockRejectedValueOnce(new Error("boom"));
    spy.mockResolvedValueOnce({
      assistant_message: "ok now",
      session_id: "s1",
      intent: null,
      awaiting_clarification: false,
    });

    const { result } = renderHook(() => useChat(), { wrapper });

    await act(async () => {
      result.current.sendMessage("Hello");
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());

    await act(async () => {
      result.current.retryLastMessage();
    });

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(spy).toHaveBeenCalledTimes(2);
    // TanStack Query's mutationFn is invoked with an internal second argument
    // (mutation context) we don't control — only assert on the first.
    expect(spy.mock.calls[1]?.[0]).toBe("Hello");
    expect(result.current.messages.filter((message) => message.role === "user")).toHaveLength(1);
  });

  it("does nothing when retryLastMessage is called before any message was sent", async () => {
    const spy = vi.spyOn(chatApi, "postChatMessage");
    const { result } = renderHook(() => useChat(), { wrapper });

    act(() => {
      result.current.retryLastMessage();
    });

    expect(spy).not.toHaveBeenCalled();
  });
});
