import { ApiError, httpError } from "./errors";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Readonly<Record<string, string | number | boolean | null | undefined>>;
  body?: JsonValue;
  accessToken?: string;
  signal?: AbortSignal;
}
export type Decoder<T> = (data: unknown) => T;
type Fetch = typeof globalThis.fetch;

export function createApiClient(baseUrl: string, fetcher: Fetch = globalThis.fetch.bind(globalThis)) {
  let base: URL;
  try {
    base = new URL(baseUrl);
    if (/[\s*]/.test(baseUrl) || !["http:", "https:"].includes(base.protocol)
      || base.username || base.password || base.search || base.hash || base.pathname !== "/"
      || base.port === "0") throw new Error();
  } catch {
    throw new ApiError("invalid_request", "Endereço da API inválido.");
  }

  async function send(path: string, options: RequestOptions): Promise<Response> {
    let url: URL;
    let body: string | undefined;
    const headers = new Headers({ Accept: "application/json" });
    try {
      if (!path.startsWith("/") || path.startsWith("//") || /[\\?#\s]/.test(path)) throw new Error();
      url = new URL(path, base);
      if (url.origin !== base.origin) throw new Error();
      for (const [key, value] of Object.entries(options.query ?? {})) {
        if (value !== null && value !== undefined) {
          if (typeof value === "number" && !Number.isFinite(value)) throw new Error();
          url.searchParams.set(key, String(value));
        }
      }
      if (options.body !== undefined) {
        if ((options.method ?? "GET") === "GET") throw new Error();
        body = JSON.stringify(options.body, (_key, value: unknown) => {
          if (typeof value === "number" && !Number.isFinite(value)) throw new Error();
          return value;
        });
        headers.set("Content-Type", "application/json");
      }
      if (options.accessToken) headers.set("Authorization", `Bearer ${options.accessToken}`);
    } catch {
      throw new ApiError("invalid_request", "Não foi possível preparar a requisição.");
    }
    let response: Response;
    try {
      response = await fetcher(url, {
        method: options.method ?? "GET", headers, body, signal: options.signal,
        credentials: "omit", redirect: "error", cache: "no-store",
      });
    } catch {
      if (options.signal?.aborted) throw new ApiError("cancelled", "Operação cancelada.");
      throw new ApiError("network", "Não foi possível conectar ao serviço. Verifique a conexão.");
    }
    if (!response.ok) {
      let payload: unknown;
      try { payload = await response.json(); } catch { /* HTTP status remains authoritative. */ }
      throw httpError(response.status, payload, response.headers.get("Retry-After"));
    }
    return response;
  }

  return {
    async request<T>(path: string, decode: Decoder<T>, options: RequestOptions = {}): Promise<T> {
      const response = await send(path, options);
      try {
        const contentType = response.headers.get("Content-Type")?.split(";")[0].trim();
        if (contentType !== "application/json") throw new Error();
        const data: unknown = await response.json();
        return decode(data);
      } catch {
        if (options.signal?.aborted) throw new ApiError("cancelled", "Operação cancelada.");
        throw new ApiError("invalid_response", "O serviço retornou uma resposta inesperada.", response.status);
      }
    },
    async requestNoContent(path: string, options: RequestOptions = {}): Promise<void> {
      const response = await send(path, options);
      if (response.status !== 204) {
        throw new ApiError("invalid_response", "O serviço retornou uma resposta inesperada.", response.status);
      }
    },
  };
}
