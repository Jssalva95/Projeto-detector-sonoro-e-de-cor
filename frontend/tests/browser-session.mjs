// Windows browser integration. Uses the existing ADMIN account without writing database records.
// Run from the repository root: node frontend/tests/browser-session.mjs
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const env = {};
for (const line of (await readFile('.env', 'utf8')).split(/\r?\n/)) {
  const match = /^(ADMIN_EMAIL|ADMIN_PASSWORD|VITE_API_BASE_URL|FRONTEND_PORT)=(.*)$/.exec(line);
  if (match) env[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/, '$2');
}
assert.ok(env.ADMIN_EMAIL && env.ADMIN_PASSWORD && env.VITE_API_BASE_URL && env.FRONTEND_PORT, 'Required local test configuration missing');
const origin = new URL(env.VITE_API_BASE_URL);
origin.port = env.FRONTEND_PORT;
const url = origin.origin;
await mkdir('.tools', { recursive: true });
const profile = await mkdtemp(join(process.cwd(), '.tools', 'session-browser-'));
const browser = spawn(process.env.EDGE_PATH ?? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', [
  '--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
  '--remote-debugging-address=127.0.0.1', '--user-data-dir=' + profile, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
let socket;
let nextId = 0;
let sessionId;
const pending = new Map();
const errors = [];
function command(method, params = {}, target = sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
    pending.set(id, { resolve: value => { clearTimeout(timeout); resolve(value); },
      reject: () => { clearTimeout(timeout); reject(new Error('CDP command failed: ' + method)); } });
    socket.send(JSON.stringify({ id, method, params, sessionId: target }));
  });
}
async function evaluate(expression) {
  const result = await command('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  assert.ok(!result.exceptionDetails, 'Browser script failed (details suppressed to protect credentials)');
  return result.result.value;
}
async function until(expression) {
  for (let i = 0; i < 100; i++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Browser state did not become ready');
}
async function capture(name) {
  const shot = await command('Page.captureScreenshot', { format: 'png' });
  await writeFile(join('.tools', name + '.png'), Buffer.from(shot.data, 'base64'));
}
async function reload() {
  await evaluate('window.__documentBeforeReload = true');
  await command('Page.reload');
  // Page.reload can return while the old DOM is still visible.
  await until("!window.__documentBeforeReload && document.readyState === 'complete'");
}
async function loginFromForm() {
  await evaluate(`(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (const [id, value] of ${JSON.stringify([['email', env.ADMIN_EMAIL], ['password', env.ADMIN_PASSWORD]])}) {
      const input = document.getElementById(id); setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    document.querySelector('form').requestSubmit();
  })()`);
}
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(port, 'Browser did not start');
  const info = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  socket = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push('runtime-error');
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    message.error ? waiter.reject() : waiter.resolve(message.result);
  };
  const target = await command('Target.createTarget', { url: 'about:blank' }, undefined);
  ({ sessionId } = await command('Target.attachToTarget', { targetId: target.targetId, flatten: true }, undefined));
  await command('Page.enable'); await command('Runtime.enable'); await command('Network.enable');
  await command('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  await command('Page.navigate', { url: url + '/session' });
  await until("location.pathname === '/login' && !!document.querySelector('#password')");
  await command('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await command('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  assert.ok(await evaluate("document.activeElement?.id === 'email'"), 'Login keyboard focus missing');
  await capture('session-login-desktop');
  await loginFromForm();
  await until("location.pathname === '/session' && document.querySelector('h1')?.textContent === 'Minha sessão'");
  assert.ok(await evaluate("!document.cookie.includes('mm_') && localStorage.length === 0 && sessionStorage.length === 0"), 'Tokens exposed in JS storage');
  let cookies = (await command('Network.getAllCookies')).cookies;
  assert.ok(cookies.filter(c => c.name === 'mm_access' || c.name === 'mm_refresh').length === 2, 'Missing session cookies');
  assert.ok(cookies.filter(c => c.name.startsWith('mm_')).every(c => c.httpOnly && c.sameSite === 'Strict'), 'Cookie protection missing');
  const originalRefresh = cookies.find(c => c.name === 'mm_refresh');
  // Navigation uses React Router and keeps the document/session alive.
  await evaluate("window.__navigationProbe = true; document.querySelector('nav a[href=\"/dashboard\"]').click()");
  await until("location.pathname === '/dashboard'");
  assert.ok(await evaluate('window.__navigationProbe === true'), 'Navigation reloaded document');
  await reload();
  await until("location.pathname === '/dashboard' && !!document.querySelector('nav')");
  // Temporary connectivity loss must not clear the browser's credentials.
  await command('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await evaluate("window.dispatchEvent(new Event('focus'))");
  await until("document.querySelector('h1')?.textContent === 'Não foi possível continuar'");
  assert.ok((await command('Network.getAllCookies')).cookies.some(c => c.name === 'mm_refresh'), 'Network failure cleared credentials');
  await command('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await evaluate("window.dispatchEvent(new Event('online'))");
  await until("location.pathname === '/dashboard' && !!document.querySelector('nav')");
  // Force only the browser's access cookie to expire; keep real refresh credentials.
  await command('Network.deleteCookies', { name: 'mm_access', domain: origin.hostname, path: '/api/v1/auth/browser' });
  await reload();
  await until("location.pathname === '/dashboard' && !!document.querySelector('nav')");
  cookies = (await command('Network.getAllCookies')).cookies;
  assert.ok(cookies.some(c => c.name === 'mm_access'), 'Access was not renewed');
  const retained = cookies.find(c => c.name === 'mm_refresh');
  assert.ok(retained?.value === originalRefresh.value && retained.expires === originalRefresh.expires, 'Refresh lifetime changed');
  // A valid access still restores after refresh expiry/removal.
  await command('Network.deleteCookies', { name: 'mm_refresh', domain: origin.hostname, path: '/api/v1/auth/browser' });
  await reload();
  await until("location.pathname === '/dashboard' && !!document.querySelector('nav')");
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("document.querySelector('nav a[href=\"/session\"]').click()");
  await until("document.querySelector('h1')?.textContent === 'Minha sessão'");
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow');
  await capture('session-account-mobile');
  // No access or refresh left: F5 must request a new login.
  await command('Network.deleteCookies', { name: 'mm_access', domain: origin.hostname, path: '/api/v1/auth/browser' });
  await reload();
  await until("location.pathname === '/login' && !!document.querySelector('#password')");
  await loginFromForm();
  await until("location.pathname === '/session' && !!document.querySelector('nav')");
  // Missing CSRF header must not clear a logged-in session.
  const csrf = await evaluate(`fetch(${JSON.stringify(env.VITE_API_BASE_URL + '/api/v1/auth/browser/logout')}, {method:'POST',credentials:'include'}).then(r=>r.status)`);
  assert.equal(csrf, 403);
  const firstSession = sessionId;
  const secondTarget = await command('Target.createTarget', { url: 'about:blank' }, undefined);
  const second = await command('Target.attachToTarget', { targetId: secondTarget.targetId, flatten: true }, undefined);
  sessionId = second.sessionId;
  await command('Page.enable'); await command('Runtime.enable');
  await command('Page.navigate', { url: url + '/session' });
  await until("document.querySelector('h1')?.textContent === 'Minha sessão'");
  sessionId = firstSession;
  await evaluate("document.querySelector('header button').click()");
  await until("location.pathname === '/login' && !!document.querySelector('#password')");
  sessionId = second.sessionId;
  await until("location.pathname === '/login' && !!document.querySelector('#password')");
  sessionId = firstSession;
  assert.ok(!(await command('Network.getAllCookies')).cookies.some(c => c.name.startsWith('mm_')), 'Logout did not clear cookies');
  await reload();
  await until("location.pathname === '/login' && !!document.querySelector('#password')");
  assert.equal(errors.length, 0, 'Unhandled browser exceptions');
  console.log('PASS: login, keyboard focus, client navigation, F5, network recovery, access renewal, fixed refresh lifetime, access-only restoration, expired session, HttpOnly, CSRF, mobile layout, logout across tabs and reload.');
} finally {
  if (socket?.readyState === WebSocket.OPEN) { await command('Browser.close').catch(() => {}); socket.close(); }
  browser.kill();
}
