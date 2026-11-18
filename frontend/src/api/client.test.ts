import { expect, test, vi } from "vitest";
import { createApiClient } from "./client";
import { ApiError } from "./errors";
import { decodeHealth } from "./index";

const BASE = "http://api.example.invalid";
const json = (data: unknown, status = 200, headers = {}) => new Response(JSON.stringify(data), {
  status, headers: { "Content-Type": "application/json", ...headers },
});

test.each(["invalid-secret", "http://user:secret@api.invalid", "http://api.invalid:0", "ftp://api.invalid"])(
  "invalid base configuration is sanitized: %s", (base) => {
    expect(() => createApiClient(base)).toThrow("Endereço da API inválido.");
  });

test("typed response, query encoding, explicit bearer, no cookies or redirects", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ status: "ok" }));
  const api = createApiClient(BASE, fetcher);
  expect(await api.request("/health", decodeHealth, { accessToken: "fixture-token", query: {
    sound_detected: false, offset: 0, name: "máquina & azul", missing: undefined, empty: null,
  } })).toEqual({ status: "ok" });
  const [url, init] = fetcher.mock.calls[0];
  expect(String(url)).toContain("sound_detected=false&offset=0&name=");
  expect(String(url)).not.toContain("missing");
  expect(String(url)).not.toContain("fixture-token");
  expect(init?.headers).toBeInstanceOf(Headers);
  expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer fixture-token");
  expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  expect(init).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store" });
});

test.each([401, 403, 404, 409, 422, 429, 500, 503])("HTTP %s is classified without leaking the body or retrying", async (status) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ detail: "secret-value" }, status));
  const api = createApiClient(BASE, fetcher);
  try {
    await api.request("/api/v1/machines", decodeHealth, { method: "POST", body: { name: "Fixture" } });
    expect.fail("Expected rejection");
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "http", status });
    expect(String(error)).not.toContain("secret-value");
    expect(JSON.stringify(error)).not.toContain("secret-value");
  }
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test("validation diagnostics keep field location/type only", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ detail: [
    { loc: ["body", "name"], type: "value_error", msg: "secret-value", input: "secret-value", ctx: { error: "secret-value" } },
  ] }, 422));
  await expect(createApiClient(BASE, fetcher).request("/api/v1/machines", decodeHealth)).rejects.toMatchObject({
    issues: [{ location: ["body", "name"], type: "value_error" }],
  });
});

test("Retry-After is available without automatic resubmission", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({}, 429, { "Retry-After": "300" }));
  await expect(createApiClient(BASE, fetcher).request("/api/v1/alert-tests", decodeHealth))
    .rejects.toMatchObject({ kind: "http", status: 429, retryAfterSeconds: 300 });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test("non-JSON HTTP errors retain status", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("proxy secret", { status: 503 }));
  await expect(createApiClient(BASE, fetcher).request("/ready", decodeHealth))
    .rejects.toMatchObject({ kind: "http", status: 503 });
});

test.each([() => json({ status: "wrong" }), () => new Response("<html>private</html>"),
  () => new Response("{broken", { headers: { "Content-Type": "application/json" } }),
])("malformed success is not presented as valid data", async (response) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response());
  await expect(createApiClient(BASE, fetcher).request("/health", decodeHealth))
    .rejects.toMatchObject({ kind: "invalid_response" });
});

test("network failure and intentional cancellation are distinct", async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new Error("internal-sensitive-detail"));
  const api = createApiClient(BASE, fetcher);
  await expect(api.request("/health", decodeHealth)).rejects.toMatchObject({ kind: "network" });
  const controller = new AbortController();
  controller.abort();
  await expect(api.request("/health", decodeHealth, { signal: controller.signal }))
    .rejects.toMatchObject({ kind: "cancelled" });
});

test.each(["https://evil.invalid", "//evil.invalid", "/\\evil.invalid", "/path?token=hidden"])(
  "rejects unsafe target %s before sending bearer", async (path) => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(createApiClient(BASE, fetcher).request(path, decodeHealth, { accessToken: "fixture" }))
      .rejects.toMatchObject({ kind: "invalid_request" });
    expect(fetcher).not.toHaveBeenCalled();
  });

test("nonfinite body rejected and DELETE 204 handled without JSON parsing", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
  const api = createApiClient(BASE, fetcher);
  await expect(api.request("/api/v1/machines", decodeHealth, { method: "POST", body: { value: Infinity } }))
    .rejects.toMatchObject({ kind: "invalid_request" });
  expect(fetcher).not.toHaveBeenCalled();
  await expect(api.requestNoContent("/api/v1/machines/1", { method: "DELETE" })).resolves.toBeUndefined();
});
