import { isRecord } from "../api/errors";

export type Role = "ADMIN" | "OPERATOR" | "VIEWER";
export interface SessionUser {
  id: number;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
}
export interface BrowserSession {
  access_token: string;
  expires_in: number;
  token_type: "bearer";
  user: SessionUser;
}

export function decodeUser(data: unknown): SessionUser {
  if (!isRecord(data) || typeof data.id !== "number" || !Number.isSafeInteger(data.id) || data.id <= 0
    || typeof data.name !== "string" || typeof data.email !== "string"
    || (data.role !== "ADMIN" && data.role !== "OPERATOR" && data.role !== "VIEWER")
    || typeof data.is_active !== "boolean") throw new Error("Invalid user response");
  return { id: data.id, name: data.name, email: data.email, role: data.role, is_active: data.is_active };
}

export function decodeSession(data: unknown): BrowserSession {
  if (!isRecord(data) || typeof data.access_token !== "string" || !data.access_token
    || data.token_type !== "bearer" || typeof data.expires_in !== "number"
    || !Number.isSafeInteger(data.expires_in) || data.expires_in <= 0) throw new Error("Invalid session response");
  return { access_token: data.access_token, expires_in: data.expires_in,
    token_type: "bearer", user: decodeUser(data.user) };
}
