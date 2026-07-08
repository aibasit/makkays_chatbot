import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ClarificationOptions from "../../src/components/ClarificationOptions";

describe("ClarificationOptions", () => {
  it("test_clarification_options_parses_bullet_lines_correctly", () => {
    const message = "Which do you mean?\n- Sales question\n- Support question";
    render(<ClarificationOptions message={message} onSelect={() => {}} />);

    const options = screen.getAllByTestId("clarification-option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("Sales question");
    expect(options[1]).toHaveTextContent("Support question");
    expect(screen.getByText("Which do you mean?")).toBeInTheDocument();
  });

  it("parses numbered-list lines as options too", () => {
    const message = "Pick one:\n1. First option\n2. Second option";
    render(<ClarificationOptions message={message} onSelect={() => {}} />);

    const options = screen.getAllByTestId("clarification-option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("First option");
    expect(options[1]).toHaveTextContent("Second option");
  });

  it("test_clarification_options_clickable_chip_calls_send_message", async () => {
    const onSelect = vi.fn();
    render(<ClarificationOptions message={"Pick one:\n1. First option\n2. Second option"} onSelect={onSelect} />);

    await userEvent.click(screen.getByText("First option"));

    expect(onSelect).toHaveBeenCalledWith("First option");
  });
});
