import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import MessageInput from "../../src/components/MessageInput";

describe("MessageInput", () => {
  it("test_message_input_disabled_while_loading", () => {
    render(<MessageInput onSend={() => {}} isLoading={true} />);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("test_message_input_disabled_when_empty", () => {
    render(<MessageInput onSend={() => {}} isLoading={false} />);
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("enables send once text is entered and calls onSend with the text", async () => {
    const onSend = vi.fn();
    render(<MessageInput onSend={onSend} isLoading={false} />);

    const input = screen.getByRole("textbox");
    await userEvent.type(input, "Hello there");
    expect(screen.getByRole("button", { name: /send/i })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith("Hello there");
  });

  it("shows a character counter once past 80% of max length", async () => {
    render(<MessageInput onSend={() => {}} isLoading={false} maxLength={10} />);

    const input = screen.getByRole("textbox");
    await userEvent.type(input, "12345678");

    expect(screen.getByText("8/10")).toBeInTheDocument();
  });
});
