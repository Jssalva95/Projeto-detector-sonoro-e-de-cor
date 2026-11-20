import { createApiClient, type Decoder, type RequestOptions } from "../api/client";
import { ApiError } from "../api/errors";
import type { BrowserSession, SessionUser } from "./contracts";

export interface AuthTransport {
  login(email: string, password: string): Promise<BrowserSession>;
  restore(): Promise<BrowserSession>;
  logout(): Promise<void>;
}
export interface SessionState {
  status: "loading" | "anonymous" | "authenticated" | "unavailable" | "logging-out";
  user: SessionUser | null;
  message?: string;
}
export interface SessionPlatform {
  now(): number;
  logoutPending(): boolean;
  setLogoutPending(pending: boolean): void;
  exclusive<T>(work: () => Promise<T>): Promise<T>;
  notify(event: "login" | "logout"): void;
}
type ProtectedOptions = Omit<RequestOptions, "accessToken" | "browserSession">;
const unauthorized = (error: unknown) => error instanceof ApiError && error.status === 401;
const cancelled = () => new ApiError("cancelled", "A sessão mudou. Tente novamente.");

/** Tokens are private memory, never part of React state or browser storage. */
export class SessionController {
  private state: SessionState = { status: "loading", user: null };
  private listeners = new Set<() => void>();
  private token: string | null = null;
  private expiresAt = 0;
  private generation = 0;
  private queue: Promise<unknown> = Promise.resolve();
  private restoring: Promise<void> | null = null;
  private loggingOut: Promise<void> | null = null;

  constructor(private auth: AuthTransport, private api: ReturnType<typeof createApiClient>,
    private platform: SessionPlatform) {}

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  remaining = () => Math.max(0, this.expiresAt - this.platform.now());

  private publish(state: SessionState) { this.state = state; this.listeners.forEach(listener => listener()); }
  private clear() { this.token = null; this.expiresAt = 0; }
  private serial<T>(work: () => Promise<T>): Promise<T> {
    const result = this.queue.then(() => this.platform.exclusive(work));
    this.queue = result.catch(() => undefined);
    return result;
  }
  private accept(result: BrowserSession, started: number, generation: number) {
    if (generation !== this.generation) throw cancelled();
    if (!result.user.is_active) throw new ApiError("http", "Sessão encerrada.", 401);
    this.token = result.access_token;
    // Conservative deadline: network latency never adds time to server validity.
    this.expiresAt = started + result.expires_in * 1000;
    this.publish({ status: "authenticated", user: result.user });
  }

  restore = (): Promise<void> => {
    if (this.loggingOut) return this.loggingOut;
    if (this.platform.logoutPending()) return this.logout();
    if (this.restoring) return this.restoring;
    const generation = this.generation;
    const task = this.serial(async () => {
      if (generation !== this.generation) throw cancelled();
      const started = this.platform.now();
      try {
        this.accept(await this.auth.restore(), started, generation);
      } catch (error) {
        if (generation !== this.generation) return;
        if (unauthorized(error)) {
          const hadSession = this.token !== null;
          this.clear();
          this.publish({ status: "anonymous", user: null,
            ...(hadSession ? { message: "Sua sessão terminou. Entre novamente." } : {}) });
        } else {
          // Keep cookies; a network/503/configuration failure is not logout.
          this.publish({ status: "unavailable", user: null,
            message: "Não foi possível verificar sua sessão. Verifique a conexão e tente novamente." });
        }
      }
    });
    this.restoring = task;
    void task.finally(() => { if (this.restoring === task) this.restoring = null; }).catch(() => undefined);
    return task;
  };

  login = async (email: string, password: string): Promise<void> => {
    const generation = ++this.generation;
    this.clear();
    this.publish({ status: "loading", user: null });
    await this.serial(async () => {
      if (generation !== this.generation) throw cancelled();
      const started = this.platform.now();
      try {
        const result = await this.auth.login(email, password);
        if (generation !== this.generation) throw cancelled();
        this.platform.setLogoutPending(false);
        this.accept(result, started, generation);
        this.platform.notify("login");
      } catch (error) {
        if (generation === this.generation) {
          this.publish({ status: "anonymous", user: null,
            message: unauthorized(error) ? "Email ou senha inválidos, ou usuário inativo." :
              "Não foi possível entrar. Verifique a conexão e tente novamente." });
        }
        throw error;
      }
    });
  };

  logout = (): Promise<void> => {
    if (this.loggingOut) return this.loggingOut;
    ++this.generation;
    this.clear();
    this.platform.setLogoutPending(true);
    this.platform.notify("logout");
    this.publish({ status: "logging-out", user: null });
    // Cookie mutations are serialized: a late refresh cannot undo logout in this tab.
    const task = this.serial(async () => {
      try {
        await this.auth.logout();
        this.platform.setLogoutPending(false);
        this.publish({ status: "anonymous", user: null });
      } catch {
        this.publish({ status: "unavailable", user: null,
          message: "A saída ainda não foi confirmada pelo servidor. Tente novamente para limpar os cookies." });
      }
    });
    this.loggingOut = task;
    void task.finally(() => { if (this.loggingOut === task) this.loggingOut = null; }).catch(() => undefined);
    return task;
  };

  externalChange = (event: "login" | "logout") => {
    ++this.generation;
    this.clear();
    this.restoring = null;
    if (event === "logout") {
      this.platform.setLogoutPending(true);
      this.publish({ status: "anonymous", user: null });
    } else {
      this.platform.setLogoutPending(false);
      this.publish({ status: "loading", user: null });
      void this.restore().catch(() => undefined);
    }
  };

  private async access(): Promise<string> {
    if (this.state.status !== "authenticated" || !this.token || this.remaining() === 0) await this.restore();
    if (this.state.status !== "authenticated" || !this.token) {
      throw new ApiError("http", "Não foi possível validar a sessão.", this.state.status === "anonymous" ? 401 : 503);
    }
    return this.token;
  }

  private async authorized<T>(operation: (token: string) => Promise<T>, retryRead: boolean): Promise<T> {
    const generation = this.generation;
    const token = await this.access();
    if (generation !== this.generation) throw cancelled();
    try {
      const result = await operation(token);
      if (generation !== this.generation) throw cancelled();
      return result;
    } catch (error) {
      if (generation !== this.generation) throw cancelled();
      if (!unauthorized(error)) throw error;
      // A concurrent request may already have renewed the same expired access.
      if (this.token === token) await this.restore();
      if (!retryRead) throw error; // Never automatically repeat a mutation.
      if (this.state.status !== "authenticated" || !this.token) throw error;
      const renewed = this.token;
      if (generation !== this.generation) throw cancelled();
      let result: T;
      try {
        result = await operation(renewed); // One retry only, never a refresh loop.
      } catch (retryError) {
        if (generation !== this.generation) throw cancelled();
        if (unauthorized(retryError)) {
          this.clear();
          this.publish({ status: "anonymous", user: null, message: "Sua sessão terminou. Entre novamente." });
        }
        throw retryError;
      }
      if (generation !== this.generation) throw cancelled();
      return result;
    }
  }

  request<T>(path: string, decoder: Decoder<T>, options: ProtectedOptions = {}): Promise<T> {
    return this.authorized(token => this.api.request(path, decoder, { ...options, accessToken: token }),
      (options.method ?? "GET") === "GET");
  }
  requestNoContent(path: string, options: ProtectedOptions): Promise<void> {
    return this.authorized(token => this.api.requestNoContent(path, { ...options, accessToken: token }), false);
  }
}
