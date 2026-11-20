import { createApiClient } from "../api/client";
import { decodeSession } from "./contracts";

export function browserAuth(api: ReturnType<typeof createApiClient>) {
  const options = { method: "POST", browserSession: true } as const;
  return {
    login: (email: string, password: string) => api.request("/api/v1/auth/browser/login", decodeSession,
      { ...options, body: { email, password } }),
    restore: () => api.request("/api/v1/auth/browser/session", decodeSession, options),
    logout: () => api.requestNoContent("/api/v1/auth/browser/logout", options),
  };
}
