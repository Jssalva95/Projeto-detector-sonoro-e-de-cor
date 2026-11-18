import { readPublicConfig } from "../config";
import { createApiClient } from "./client";
import { isRecord } from "./errors";

export interface HealthResponse { status: "ok" }

export function decodeHealth(data: unknown): HealthResponse {
  if (!isRecord(data) || data.status !== "ok") throw new Error("Invalid health response");
  return { status: "ok" };
}

// Instantiated explicitly by consumers; no requests or WebSocket connections on import.
export function configuredApi() {
  return createApiClient(readPublicConfig(import.meta.env).apiBaseUrl);
}
