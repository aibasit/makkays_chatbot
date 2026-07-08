import { beforeEach, describe, expect, it, vi } from "vitest";

describe("api client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("test_axios_instance_sends_site_api_key_header", async () => {
    vi.stubEnv("VITE_SITE_API_KEY", "test-key");
    const { apiClient } = await import("../../src/api/client");

    const headers = apiClient.defaults.headers as unknown as Record<string, string>;
    expect(headers["X-Site-Api-Key"]).toBe("test-key");
  });

  it("test_axios_instance_has_with_credentials_true", async () => {
    const { apiClient } = await import("../../src/api/client");

    expect(apiClient.defaults.withCredentials).toBe(true);
  });

  it("defaults the base URL and timeout sensibly", async () => {
    const { apiClient } = await import("../../src/api/client");

    expect(apiClient.defaults.baseURL).toBe("http://localhost:8000");
    expect(apiClient.defaults.timeout).toBe(30000);
  });
});
