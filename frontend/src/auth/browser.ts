import { createApiClient } from "../api/client";
import { readPublicConfig } from "../config";
import { SessionController, type SessionPlatform } from "./session";
import { browserAuth } from "./transport";

export function createBrowserSession() {
  const config = readPublicConfig(import.meta.env);
  const apiUrl = new URL(config.apiBaseUrl);
  if (apiUrl.hostname !== window.location.hostname || apiUrl.protocol !== window.location.protocol) {
    throw new Error("Frontend and API require matching scheme and hostname");
  }
  const api = createApiClient(config.apiBaseUrl);
  const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("machine-monitor-session");
  const marker = "machine-monitor-logout-pending";
  let pending = false;
  const platform: SessionPlatform = {
    now: Date.now,
    logoutPending: () => { try { return pending || sessionStorage.getItem(marker) === "1"; } catch { return pending; } },
    setLogoutPending: value => {
      pending = value;
      // Only a non-secret logout marker; never a JWT or user data.
      try { if (value) sessionStorage.setItem(marker, "1"); else sessionStorage.removeItem(marker); } catch { /* Memory fallback. */ }
    },
    exclusive: work => navigator.locks ? navigator.locks.request("machine-monitor-cookie-session", work) : work(),
    notify: event => channel?.postMessage(event),
  };
  const controller = new SessionController(browserAuth(api), api, platform);
  if (channel) channel.onmessage = message => {
    if (message.data === "login" || message.data === "logout") controller.externalChange(message.data);
  };
  return { controller, dispose: () => channel?.close() };
}
