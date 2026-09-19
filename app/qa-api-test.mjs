// Manual-only smoke of the BFF proxy layer: register, create a workspace,
// upload a file through /api/files, read /api/notifications.
// Run: node qa-api-test.mjs  (needs the app on :3000 and backend :8000 up)
//
// Every response status is checked and the process exits non-zero on a failure.
// It used to discard all four statuses, so it printed a body and exited 0 even
// when the proxy answered 500 — a script that cannot fail is not a test.

const API_BASE = 'http://127.0.0.1:8000';
const PROXY_BASE = 'http://localhost:3000';
const email = `api.qa.${Date.now()}@test.com`;
const failures = [];

function check(label, ok, detail) {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label} — ${detail}`);
  if (!ok) failures.push(label);
}

const register = await fetch(`${API_BASE}/auth/register`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password: 'TestPass123!', name: 'API QA' })
});
const token = (await register.json().catch(() => ({})))?.access_token;
check('register', register.status === 201 && !!token, `status=${register.status}`);
if (!token) {
  process.exitCode = 1;
} else {
  const slug = `qa-${Date.now()}`;
  const workspace = await fetch(`${API_BASE}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name: 'QA Workspace', slug })
  });
  check('create-workspace', workspace.status === 201, `status=${workspace.status}`);

  const form = new FormData();
  form.append('file', new Blob(['QA test content'], { type: 'text/plain' }), 'api-test.txt');
  const upload = await fetch(`${PROXY_BASE}/api/files`, {
    method: 'POST',
    headers: { Cookie: `session_token=${token}` },
    body: form
  });
  check('proxy-upload', upload.status >= 200 && upload.status < 300, `status=${upload.status}`);

  const notifications = await fetch(`${PROXY_BASE}/api/notifications`, {
    headers: { Cookie: `session_token=${token}` }
  });
  const body = await notifications.json().catch(() => null);
  check('proxy-notifications', notifications.status === 200, `status=${notifications.status}`);
  console.log('notifications body:', JSON.stringify(body).slice(0, 200));

  process.exitCode = failures.length > 0 ? 1 : 0;
}
