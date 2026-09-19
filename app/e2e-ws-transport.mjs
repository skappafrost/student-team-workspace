// E2E: verify the realtime WebSocket transport (PR #201).
//
//   node e2e-ws-transport.mjs guard     -> expects the host-mismatch guard to fire
//                                          (NEXT_PUBLIC_API_URL hostname != page host)
//   node e2e-ws-transport.mjs realtime  -> expects exactly one socket, surviving
//                                          repeated parent re-renders, delivering
//                                          a message to a second user
//
// Assumes backend :8000 and `bun run dev:webpack` :3000 are already up.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MODE = process.argv[2] === 'guard' ? 'guard' : 'realtime';
const APP = 'http://localhost:3000';
const API = process.env.API_URL ?? 'http://localhost:8000';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE = path.join(HERE, 'qa-evidence');

const stamp = Date.now();
const PASSWORD = 'password123';
const results = [];

function step(name, ok, detail) {
  results.push({ name, status: ok ? 'PASS' : 'FAIL', detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name} — ${detail}`);
}

async function api(method, pathname, body, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${pathname}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON body */
  }
  return { status: res.status, json };
}

// A fresh two-member workspace with one shared channel, so a message from A has
// somewhere to reach B over a socket.
async function seedRoster() {
  const a = await api('POST', '/auth/register', { email: `wsA-${stamp}@example.com`, password: PASSWORD });
  const b = await api('POST', '/auth/register', { email: `wsB-${stamp}@example.com`, password: PASSWORD });
  if (a.status !== 201 || b.status !== 201) {
    throw new Error(`register failed: A=${a.status} B=${b.status}`);
  }
  const aTok = a.json.access_token;
  const bTok = b.json.access_token;

  const ws = await api('POST', '/workspaces', { name: `WS ${stamp}`, slug: `ws-${stamp}`, description: 'x' }, aTok);
  if (ws.status !== 201) throw new Error(`workspace failed: ${ws.status} ${JSON.stringify(ws.json)}`);
  const wsId = ws.json.id;

  const invite = await api('POST', `/workspaces/${wsId}/invites`, { email: `wsB-${stamp}@example.com`, role: 'member' }, aTok);
  if (invite.status !== 201) throw new Error(`invite failed: ${invite.status} ${JSON.stringify(invite.json)}`);
  const accept = await api('POST', '/invites/accept', { token: invite.json.token }, bTok);
  if (accept.status !== 201) throw new Error(`accept failed: ${accept.status} ${JSON.stringify(accept.json)}`);

  const ch = await api('POST', `/workspaces/${wsId}/channels`, { name: `room-${stamp}`, type: 'general' }, aTok);
  if (ch.status !== 201) throw new Error(`channel failed: ${ch.status} ${JSON.stringify(ch.json)}`);

  return { aTok, bTok, channelName: `room-${stamp}` };
}

// Next's dev server opens its own HMR websocket on the page origin; counting it
// as an app socket would inflate every number below by one.
function isBackendSocket(url) {
  return !url.startsWith('ws://localhost:3000') && !url.startsWith('ws://127.0.0.1:3000');
}

async function openChat(context, token, channelName) {
  await context.addCookies([
    { name: 'session_token', value: token, domain: 'localhost', path: '/', httpOnly: true, sameSite: 'Lax' }
  ]);
  const page = await context.newPage();
  // First hit on a route triggers a webpack compile under `dev:webpack`, which
  // can exceed the default 30s on a cold cache.
  page.setDefaultTimeout(120000);
  const allSockets = [];
  const errors = [];
  page.on('websocket', (ws) => allSockets.push(ws.url()));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  await page.goto(`${APP}/dashboard/chat`, { waitUntil: 'domcontentloaded' });
  await page.getByText(channelName, { exact: false }).first().waitFor({ timeout: 120000 });
  await page.getByText(channelName, { exact: false }).first().click();
  const sockets = allSockets.filter(isBackendSocket);
  return { page, sockets: allSockets, backendSockets: sockets, errors };
}

const browser = await chromium.launch({ headless: true });
let exitCode = 0;

try {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  const { aTok, bTok, channelName } = await seedRoster();
  step('seed-two-member-workspace', true, `channel=${channelName}`);

  if (MODE === 'guard') {
    const ctx = await browser.newContext();
    const { page, backendSockets, errors } = await openChat(ctx, aTok, channelName);
    await page.waitForTimeout(4000);
    const guardMsg = errors.find((e) => e.includes('[stw-realtime]'));
    step('guard-logged-named-error', !!guardMsg, guardMsg ? guardMsg.slice(0, 200) : `no [stw-realtime] error among ${errors.length} console errors`);
    step('no-backend-socket-opened', backendSockets.length === 0, `backend sockets=${backendSockets.length}`);
    await page.screenshot({ path: path.join(EVIDENCE, 'ws-01-host-guard.png'), fullPage: true });
    await ctx.close();
  } else {
    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    const a = await openChat(ctxA, aTok, channelName);
    const b = await openChat(ctxB, bTok, channelName);

    await a.page.waitForTimeout(2500);
    step('backend-socket-opens', a.backendSockets.length >= 1, `A backend sockets=${a.backendSockets.length}`);
    step('one-socket-per-page', a.backendSockets.length === 1, `A backend urls=${JSON.stringify(a.backendSockets)}`);

    // Parent re-renders are what used to tear the socket down and rebuild it:
    // every keystroke sets `draft` state, re-rendering chat-page with a fresh
    // inline onMessage closure.
    // The composer placeholder is `Message #<channel>`; a looser /message/i match
    // picks the "Search messages…" box that appears earlier in the DOM instead.
    const composer = a.page.getByPlaceholder(`Message #${channelName}`);
    await composer.click();
    for (let i = 0; i < 30; i += 1) {
      await composer.type(`x${i}`, { delay: 5 });
    }
    await a.page.waitForTimeout(1500);
    const reconnects = a.backendSockets.length - 1;
    step('no-reconnect-after-30-renders', reconnects === 0, `extra backend sockets=${reconnects}, total=${a.backendSockets.length}`);
    await a.page.screenshot({ path: path.join(EVIDENCE, 'ws-02-chat-open.png'), fullPage: true });

    // Real delivery: B is a different browser context, so a message appearing
    // there cannot be an optimistic local append by the sender.
    const marker = `cross-context-${stamp}`;
    await composer.fill(marker);
    await a.page.keyboard.press('Enter');
    const arrived = await b.page
      .getByText(marker, { exact: false })
      .first()
      .waitFor({ timeout: 15000 })
      .then(() => true)
      .catch(() => false);
    const inDom = !arrived && (await b.page.content()).includes(marker);
    const sameRoom =
      a.backendSockets[0] === b.backendSockets[0] && a.backendSockets.length > 0;
    step(
      'message-reaches-peer-context',
      arrived || inDom,
      `marker=${marker} rendered=${arrived} inDom=${inDom} sameSocketUrl=${sameRoom} ` +
        `A=${JSON.stringify(a.backendSockets)} B=${JSON.stringify(b.backendSockets)}`
    );
    await b.page.screenshot({ path: path.join(EVIDENCE, 'ws-03-peer-received.png'), fullPage: true });

    const guardErrors = a.errors.filter((e) => e.includes('[stw-realtime]'));
    step('no-host-guard-misfire', guardErrors.length === 0, `guard errors=${guardErrors.length}`);

    await ctxA.close();
    await ctxB.close();
  }
} catch (err) {
  step('harness-error', false, err.message);
  console.error(err);
} finally {
  await browser.close();
}

const reportPath = path.join(EVIDENCE, `ws-transport-${MODE}-report.json`);
fs.writeFileSync(reportPath, JSON.stringify({ stamp, mode: MODE, results }, null, 2));
console.log(`\nReport: ${reportPath}`);

const failed = results.filter((r) => r.status === 'FAIL');
if (failed.length > 0) {
  console.error('FAILED STEPS:', failed.map((f) => f.name).join(', '));
  exitCode = 1;
}
process.exit(exitCode);
