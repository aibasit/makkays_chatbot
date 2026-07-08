import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessageBubble from "../../src/components/MessageBubble";

describe("MessageBubble", () => {
  it("renders user vs assistant styling correctly", () => {
    const { rerender } = render(<MessageBubble message={{ role: "user", content: "Hi" }} />);
    expect(screen.getByTestId("message-bubble")).toHaveAttribute("data-role", "user");

    rerender(<MessageBubble message={{ role: "assistant", content: "Hello there" }} />);
    expect(screen.getByTestId("message-bubble")).toHaveAttribute("data-role", "assistant");
  });
});
