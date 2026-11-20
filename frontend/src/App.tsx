import { useState, type FormEvent } from "react";
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/context";

function SessionGate() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (status !== "authenticated") return <SessionStatus />;
  return <Outlet />;
}
function SessionStatus() {
  const { status, message, controller } = useAuth();
  return <main className="centered"><section className="panel" aria-labelledby="session-title">
    <p className="brand">Machine Monitor</p>
    <h1 id="session-title">{status === "unavailable" ? "Não foi possível continuar" : "Verificando sessão"}</h1>
    <p role={status === "unavailable" ? "alert" : "status"}>
      {message ?? (status === "logging-out" ? "Encerrando o acesso…" : "Aguarde enquanto verificamos seu acesso.")}
    </p>
    {status === "unavailable" && <div className="actions">
      <button onClick={() => { void controller.restore().catch(() => undefined); }}>Tentar novamente</button>
      <button className="secondary" onClick={() => { void controller.logout(); }}>Sair</button>
    </div>}
  </section></main>;
}
function Login() {
  const { status, message, controller } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const previous = location.state as { from?: unknown } | null;
  const destination = typeof previous?.from === "string" && /^\/(?!\/)[^\\?#]*$/.test(previous.from)
    && previous.from !== "/login" ? previous.from : "/dashboard";
  if (status === "authenticated") return <Navigate to={destination} replace />;
  if (status !== "anonymous") return <SessionStatus />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const secret = password;
    setPassword("");
    try { await controller.login(email, secret); } catch { /* Sanitized message comes from the controller. */ }
  }
  return <main className="centered"><section className="panel login-panel" aria-labelledby="login-title">
    <p className="brand">Machine Monitor</p><h1 id="login-title">Acesse sua conta</h1>
    <p className="muted">Entre com seu email e senha para continuar.</p>
    {message && <p className="notice" role="status">{message}</p>}
    <form onSubmit={submit}>
      <label htmlFor="email">Email</label>
      <input id="email" name="email" type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)} />
      <label htmlFor="password">Senha</label>
      <input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} />
      <button type="submit">Entrar</button>
    </form>
  </section></main>;
}
const roles = { ADMIN: "Administrador", OPERATOR: "Operador", VIEWER: "Visualizador" };
function Layout() {
  const { user, controller } = useAuth();
  return <div className="app-shell">
    <a className="skip-link" href="#content">Ir para o conteúdo</a>
    <header className="app-header"><Link className="brand" to="/dashboard">Machine Monitor</Link>
      <div className="identity"><span>{user?.name}</span><button className="secondary" onClick={() => { void controller.logout(); }}>Sair</button></div>
    </header>
    <div className="workspace"><nav aria-label="Navegação principal">
      <NavLink to="/dashboard">Visão geral</NavLink><NavLink to="/session">Minha sessão</NavLink>
    </nav><main id="content" tabIndex={-1}><Outlet /></main></div>
  </div>;
}
function SessionPage() {
  const { user } = useAuth();
  if (!user) return null;
  return <section className="panel"><h1>Minha sessão</h1><p className="muted">Informações da conta autenticada.</p>
    <dl><dt>Nome</dt><dd>{user.name}</dd><dt>Email</dt><dd>{user.email}</dd>
      <dt>Perfil de acesso</dt><dd>{roles[user.role]}</dd></dl>
  </section>;
}
export function App() {
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<SessionGate />}><Route element={<Layout />}>
      <Route index element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<section className="panel"><h1>Visão geral</h1>
        <p>Seu acesso está ativo. O painel de monitoramento será disponibilizado na próxima etapa.</p>
      </section>} />
      <Route path="/session" element={<SessionPage />} />
      <Route path="*" element={<section className="panel"><h1>Página não encontrada</h1><Link to="/dashboard">Voltar à visão geral</Link></section>} />
    </Route></Route>
  </Routes>;
}
