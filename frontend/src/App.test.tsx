import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { App } from "./App";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "./auth/context";
import { SessionController } from "./auth/session";
import { createApiClient } from "./api/client";
import { ApiError } from "./api/errors";

test("login is labelled and does not expose private content while anonymous", async () => {
  const controller = new SessionController({ login: async () => { throw new Error(); },
    restore: async () => { throw new ApiError("http", "Fixture", 401); }, logout: async () => {} },
    createApiClient("https://api.example.invalid"), { now: Date.now, logoutPending: () => false,
      setLogoutPending: () => {}, exclusive: work => work(), notify: () => {} });
  await controller.restore();
  const html = renderToStaticMarkup(<AuthProvider controller={controller}><MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter></AuthProvider>);
  expect(html).toContain('for="email"'); expect(html).toContain('for="password"');
  expect(html).toContain('type="password"'); expect(html).toContain("Entrar");
  expect(html).not.toContain("Minha sessão");
});
