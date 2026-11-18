export interface PublicConfig {
  apiBaseUrl: string;
  websocketUrl: string;
}

export function readPublicConfig(env: Record<string, unknown>): PublicConfig {
  try {
    const apiValue = env.VITE_API_BASE_URL;
    const wsValue = env.VITE_WS_URL;
    if (typeof apiValue !== "string" || typeof wsValue !== "string"
      || /[\s*]/.test(apiValue + wsValue)) throw new Error();
    const api = new URL(apiValue);
    const ws = new URL(wsValue);
    if (!["http:", "https:"].includes(api.protocol) || api.pathname !== "/"
      || api.username || api.password || api.search || api.hash
      || api.port === "0"
      || !["ws:", "wss:"].includes(ws.protocol) || ws.pathname !== "/api/v1/ws/events"
      || ws.username || ws.password || ws.search || ws.hash
      || api.host !== ws.host || (api.protocol === "https:") !== (ws.protocol === "wss:")) {
      throw new Error();
    }
    return { apiBaseUrl: api.origin, websocketUrl: ws.href };
  } catch {
    throw new Error("Configure VITE_API_BASE_URL e VITE_WS_URL com URLs públicas válidas do backend.");
  }
}
