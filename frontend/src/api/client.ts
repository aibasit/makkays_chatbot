import axios from "axios";

// `withCredentials: true` is required so the browser sends/receives the
// HttpOnly session cookie cross-port in local dev (widget on :5173, backend on
// :8000) — without it the cookie is silently dropped and every request starts
// a new session.
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
  headers: {
    "X-Site-Api-Key": import.meta.env.VITE_SITE_API_KEY || "",
  },
  withCredentials: true,
  timeout: 30000,
});
