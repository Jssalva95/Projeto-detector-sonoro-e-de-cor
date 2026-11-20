import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./auth/context";
import { createBrowserSession } from "./auth/browser";
import "./style.css";

const root = createRoot(document.getElementById("root")!);
try {
  const session = createBrowserSession();
  if (import.meta.hot) import.meta.hot.dispose(session.dispose);
  root.render(<StrictMode><AuthProvider controller={session.controller}><BrowserRouter><App /></BrowserRouter></AuthProvider></StrictMode>);
} catch {
  root.render(<main className="centered"><section className="panel"><h1>Verifique a configuração de acesso</h1>
    <p>Frontend e API precisam usar o mesmo protocolo e hostname. Na configuração local atual, utilize localhost em ambos.</p>
    <p>Confira as URLs públicas configuradas e recarregue a página.</p></section></main>);
}
