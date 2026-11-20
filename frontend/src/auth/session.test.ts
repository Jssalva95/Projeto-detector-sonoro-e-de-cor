import { expect, test, vi } from "vitest";
import { createApiClient } from "../api/client";
import { ApiError } from "../api/errors";
import { decodeHealth } from "../api";
import { decodeSession, decodeUser, type BrowserSession } from "./contracts";
import { SessionController, type SessionPlatform } from "./session";
import { browserAuth } from "./transport";

const user = { id: 1, name: "Fixture", email: "fixture@example.invalid", role: "VIEWER" as const, is_active: true };
const session = (token = "fixture-access"): BrowserSession => ({ access_token: token, expires_in: 2, token_type: "bearer", user });
const denied = () => new ApiError("http", "Fixture", 401);
const offline = () => new ApiError("network", "Fixture");
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; }
function fixture() {
  let time = 1000;
  let pending = false;
  const auth = { login: vi.fn().mockResolvedValue(session()), restore: vi.fn().mockResolvedValue(session()), logout: vi.fn().mockResolvedValue(undefined) };
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({ status: "ok" }), { headers: { "Content-Type": "application/json" } }));
  const api = createApiClient("https://api.example.invalid", fetcher);
  const platform: SessionPlatform = { now: () => time, logoutPending: () => pending,
    setLogoutPending: value => { pending = value; }, exclusive: work => work(), notify: vi.fn() };
  const controller = new SessionController(auth, api, platform);
  return { controller, auth, fetcher, platform, advance: (amount: number) => { time += amount; } };
}

test.each([ ["ADMIN"], { toString: () => "ADMIN" }, null, 1, "admin", "SUPERUSER" ])("rejects invalid role types and values: %j", role => {
  expect(() => decodeUser({ ...user, role })).toThrow();
});
test.each(["ADMIN", "OPERATOR", "VIEWER"])("accepts the exact role %s", role => {
  expect(decodeUser({ ...user, role }).role).toBe(role);
});
test("decoder rejects unsafe IDs and malformed session envelopes", () => {
  expect(() => decodeUser({ ...user, id: Number.MAX_SAFE_INTEGER + 1 })).toThrow();
  for (const change of [{ expires_in: 0 }, { expires_in: "2" }, { access_token: "" }, { token_type: "refresh" }]) {
    expect(() => decodeSession({ ...session(), ...change })).toThrow();
  }
  expect(decodeUser({ ...user, password_hash: "private-fixture" })).not.toHaveProperty("password_hash");
});
test("browser transport uses cookies/CSRF only for browser auth endpoints", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(session()), { headers: { "Content-Type": "application/json" } }));
  const auth = browserAuth(createApiClient("https://api.example.invalid", fetcher));
  await auth.login("fixture@example.invalid", "fixture-password");
  const [url, options] = fetcher.mock.calls[0];
  expect(String(url)).toBe("https://api.example.invalid/api/v1/auth/browser/login");
  expect(options?.credentials).toBe("include");
  expect(new Headers(options?.headers).get("X-CSRF-Protection")).toBe("1");
  expect(new Headers(options?.headers).has("Authorization")).toBe(false);
});
test("restore authenticates without login and exposes no token in public state", async () => {
  const { controller, auth } = fixture();
  await controller.restore();
  expect(controller.getSnapshot()).toEqual({ status: "authenticated", user });
  expect(auth.login).not.toHaveBeenCalled();
  expect(JSON.stringify(controller.getSnapshot())).not.toContain("fixture-access");
});
test("concurrent restoration is single flight", async () => {
  const { controller, auth } = fixture();
  const result = deferred<BrowserSession>();
  auth.restore.mockReturnValue(result.promise);
  const first = controller.restore(); const second = controller.restore();
  expect(first).toBe(second);
  result.resolve(session()); await first;
  expect(auth.restore).toHaveBeenCalledTimes(1);
});
test("valid access is reused; expiry renews once for concurrent requests", async () => {
  const { controller, auth, advance, fetcher } = fixture();
  await controller.restore();
  await controller.request("/health", decodeHealth);
  expect(auth.restore).toHaveBeenCalledTimes(1);
  advance(2000);
  auth.restore.mockResolvedValue(session("renewed-fixture"));
  await Promise.all([controller.request("/health", decodeHealth), controller.request("/health", decodeHealth)]);
  expect(auth.restore).toHaveBeenCalledTimes(2);
  expect(new Headers(fetcher.mock.calls[2][1]?.headers).get("Authorization")).toBe("Bearer renewed-fixture");
});
test("expired refresh or inactive user returns to anonymous", async () => {
  const { controller, auth, advance, fetcher } = fixture();
  await controller.restore(); advance(2000);
  auth.restore.mockRejectedValue(denied());
  await expect(controller.request("/health", decodeHealth)).rejects.toMatchObject({ status: 401 });
  expect(controller.getSnapshot().status).toBe("anonymous");
  expect(fetcher).not.toHaveBeenCalled();
  auth.restore.mockResolvedValue({ ...session(), user: { ...user, is_active: false } });
  await controller.restore(); expect(controller.getSnapshot().status).toBe("anonymous");
});
test.each([offline(), new ApiError("http", "Fixture", 503)])("temporary failure preserves cookies and allows recovery", async error => {
  const { controller, auth } = fixture();
  auth.restore.mockRejectedValueOnce(error);
  await controller.restore();
  expect(controller.getSnapshot().status).toBe("unavailable");
  expect(auth.logout).not.toHaveBeenCalled();
  await controller.restore(); expect(controller.getSnapshot().status).toBe("authenticated");
});
test("401 on GET retries once, while 403 never renews", async () => {
  const { controller, auth, fetcher } = fixture();
  await controller.restore();
  fetcher.mockResolvedValueOnce(new Response("{}", { status: 401 }));
  expect(await controller.request("/health", decodeHealth)).toEqual({ status: "ok" });
  expect(auth.restore).toHaveBeenCalledTimes(2);
  fetcher.mockResolvedValueOnce(new Response("{}", { status: 403 }));
  await expect(controller.request("/health", decodeHealth)).rejects.toMatchObject({ status: 403 });
  expect(auth.restore).toHaveBeenCalledTimes(2);
});
test("mutations and network failures are not automatically resubmitted", async () => {
  const { controller, fetcher } = fixture(); await controller.restore();
  fetcher.mockResolvedValueOnce(new Response("{}", { status: 401 }));
  await expect(controller.request("/resource", decodeHealth, { method: "POST", body: {} })).rejects.toMatchObject({ status: 401 });
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockRejectedValueOnce(new Error("private-fixture"));
  await expect(controller.request("/resource", decodeHealth, { method: "POST", body: {} })).rejects.toMatchObject({ kind: "network" });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
test("logout waits for cookie response and prevents late restoration", async () => {
  const { controller, auth } = fixture(); const result = deferred<BrowserSession>();
  auth.restore.mockReturnValue(result.promise);
  const restoring = controller.restore();
  await Promise.resolve(); await Promise.resolve();
  const logout = controller.logout();
  expect(controller.getSnapshot().user).toBeNull();
  expect(auth.logout).not.toHaveBeenCalled();
  result.resolve(session()); await restoring; await logout;
  expect(auth.logout).toHaveBeenCalledTimes(1);
  expect(controller.getSnapshot().status).toBe("anonymous");
});
test("failed logout survives controller recreation without silently restoring", async () => {
  const { controller, auth, platform } = fixture(); await controller.restore();
  auth.logout.mockRejectedValueOnce(offline()); await controller.logout();
  expect(platform.logoutPending()).toBe(true);
  expect(controller.getSnapshot().status).toBe("unavailable");
  const reloaded = new SessionController(auth, createApiClient("https://api.example.invalid"), platform);
  await reloaded.restore();
  expect(auth.restore).toHaveBeenCalledTimes(1);
  expect(auth.logout).toHaveBeenCalledTimes(2);
  expect(reloaded.getSnapshot().status).toBe("anonymous");
});
test("late resource response cannot repopulate UI after logout", async () => {
  const { controller, fetcher } = fixture(); await controller.restore();
  const result = deferred<Response>(); fetcher.mockReturnValue(result.promise);
  const request = controller.request("/health", decodeHealth);
  await Promise.resolve(); await Promise.resolve();
  await controller.logout(); result.resolve(new Response('{"status":"ok"}', { headers: { "Content-Type": "application/json" } }));
  await expect(request).rejects.toMatchObject({ kind: "cancelled" });
});
test("external logout invalidates local access", async () => {
  const { controller } = fixture(); await controller.restore();
  controller.externalChange("logout"); expect(controller.getSnapshot()).toEqual({ status: "anonymous", user: null });
});

test("a second 401 ends access without an infinite retry loop", async () => {
  const { controller, fetcher, auth } = fixture(); await controller.restore();
  fetcher.mockImplementation(async () => new Response("{}", { status: 401 }));
  await expect(controller.request("/health", decodeHealth)).rejects.toMatchObject({ status: 401 });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(auth.restore).toHaveBeenCalledTimes(2);
  expect(controller.getSnapshot().status).toBe("anonymous");
});
test("late login response cannot restore the session after logout", async () => {
  const { controller, auth } = fixture(); const result = deferred<BrowserSession>();
  auth.login.mockReturnValue(result.promise);
  const login = controller.login("fixture@example.invalid", "fixture-password");
  const rejection = expect(login).rejects.toMatchObject({ kind: "cancelled" });
  await Promise.resolve(); await Promise.resolve();
  const logout = controller.logout();
  result.resolve(session());
  await rejection; await logout;
  expect(controller.getSnapshot().status).toBe("anonymous");
  expect(auth.logout).toHaveBeenCalledTimes(1);
});
test("role is refreshed from the backend, not copied from persisted client state", async () => {
  const { controller, auth } = fixture(); await controller.restore();
  auth.restore.mockResolvedValue({ ...session(), user: { ...user, role: "OPERATOR" } });
  await controller.restore();
  expect(controller.getSnapshot().user?.role).toBe("OPERATOR");
});
