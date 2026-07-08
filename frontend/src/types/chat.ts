// Hand-maintained: re-exports the backend-generated request/response types and
// adds the frontend-only `ChatMessage` shape used for local message-list state.
// Regenerate the backend types with: python scripts/generate_typescript_types.py
export type { ChatRequest, ChatResponse } from "./generated";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  awaitingClarification?: boolean;
};
