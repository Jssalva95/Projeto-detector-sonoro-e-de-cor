import { expect, test } from "vitest";
import { readPublicConfig } from "./config";

const env = { VITE_API_BASE_URL: "http://localhost:8000", VITE_WS_URL: "ws://localhost:8000/api/v1/ws/events" };

test("explicit public endpoints, including HTTPS and WSS", () => {
  expect(readPublicConfig(env).apiBaseUrl).toBe(env.VITE_API_BASE_URL);
  expect(readPublicConfig({ VITE_API_BASE_URL: "https://api.example.invalid/",
    VITE_WS_URL: "wss://api.example.invalid/api/v1/ws/events" }).apiBaseUrl).toBe("https://api.example.invalid");
});

test.each([
  {}, { VITE_API_BASE_URL: "" }, { VITE_API_BASE_URL: "http://user:secret@localhost:8000" },
  { VITE_API_BASE_URL: "http://localhost:8000/api/v1" },
  { VITE_API_BASE_URL: "http://localhost:8000?secret=hidden" },
  { VITE_API_BASE_URL: " https://localhost:8000" },
  { VITE_WS_URL: "ws://other.invalid/api/v1/ws/events" },
  { VITE_WS_URL: "ws://localhost:8000/wrong" },
  { VITE_WS_URL: "ws://localhost:8000/api/v1/ws/events?token=secret" },
  { VITE_WS_URL: "wss://localhost:8000/api/v1/ws/events" },
])("invalid public configuration fails without echoing values: %j", (changes) => {
  const input = Object.keys(changes).length ? { ...env, ...changes } : {};
  expect(() => readPublicConfig(input)).toThrow("Configure VITE_API_BASE_URL e VITE_WS_URL com URLs públicas válidas do backend.");
});
