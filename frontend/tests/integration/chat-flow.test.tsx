import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import ChatPage from "../../src/routes/ChatPage";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderChatPage() {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

describe("chat flow integration", () => {
  it("sends a message, shows it optimistically, then renders the assistant reply", async () => {
    server.use(
      http.post(`${API_BASE_URL}/chat`, async () =>
        HttpResponse.json({
          assistant_message: "We have several switches in stock.",
          session_id: "s1",
          intent: "sales_inquiry",
          awaiting_clarification: false,
        }),
      ),
    );

    renderChatPage();
    await userEvent.type(screen.getByRole("textbox"), "Do you have switches?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getByText("Do you have switches?")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("We have several switches in stock.")).toBeInTheDocument());
  });

  it("renders clarification options distinctly when awaiting_clarification is true", async () => {
    server.use(
      http.post(`${API_BASE_URL}/chat`, async () =>
        HttpResponse.json({
          assistant_message: "Do you mean:\n- Sales question\n- Support question",
          session_id: "s1",
          intent: "sales_inquiry",
          awaiting_clarification: true,
        }),
      ),
    );

    renderChatPage();
    await userEvent.type(screen.getByRole("textbox"), "help");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(screen.getAllByTestId("clarification-option")).toHaveLength(2));
  });

  it("shows the rate limit notice and disables input on 429", async () => {
    server.use(http.post(`${API_BASE_URL}/chat`, async () => new HttpResponse(null, { status: 429 })));

    renderChatPage();
    await userEvent.type(screen.getByRole("textbox"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(screen.getByTestId("rate-limit-notice")).toBeInTheDocument());
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("keeps the user's message visible and offers retry on a network error", async () => {
    server.use(http.post(`${API_BASE_URL}/chat`, () => HttpResponse.error()));

    renderChatPage();
    await userEvent.type(screen.getByRole("textbox"), "Hello");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(screen.getByTestId("error-bubble")).toBeInTheDocument());
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});
