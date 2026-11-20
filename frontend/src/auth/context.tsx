import { createContext, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";
import type { SessionController } from "./session";

const Context = createContext<SessionController | null>(null);
export function AuthProvider({ controller, children }: { controller: SessionController; children: ReactNode }) {
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  useEffect(() => {
    void controller.restore().catch(() => undefined);
    const visible = () => { if (document.visibilityState === "visible") void controller.restore().catch(() => undefined); };
    window.addEventListener("focus", visible);
    window.addEventListener("online", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("focus", visible);
      window.removeEventListener("online", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [controller]);
  useEffect(() => {
    if (state.status !== "authenticated") return;
    const timer = window.setTimeout(() => { void controller.restore().catch(() => undefined); },
      Math.min(controller.remaining(), 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [controller, state]);
  return <Context.Provider value={controller}>{children}</Context.Provider>;
}
export function useAuth() {
  const controller = useContext(Context);
  if (!controller) throw new Error("AuthProvider is required");
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  return { controller, ...state };
}
