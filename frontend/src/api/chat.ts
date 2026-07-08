import { apiClient } from "./client";
import type { ChatResponse } from "../types/chat";

// The only place Axios is called directly — components and hooks never call
// Axios themselves, they go through this thin service-layer function.
export async function postChatMessage(message: string): Promise<ChatResponse> {
  const response = await apiClient.post<ChatResponse>("/chat", { message });
  return response.data;
}
