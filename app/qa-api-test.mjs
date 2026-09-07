const API_BASE = 'http://127.0.0.1:8000';
const PROXY_BASE = 'http://localhost:3001';
const email = `api.qa.${Date.now()}@test.com`;

async function register() {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: 'TestPass123!', name: 'API QA' })
  });
  const data = await res.json();
  return data.access_token;
}

const token = await register();
const slug = `qa-${Date.now()}`;
await fetch(`${API_BASE}/workspaces`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
  body: JSON.stringify({ name: 'QA Workspace', slug })
});

const form = new FormData();
const blob = new Blob(['QA test content'], { type: 'text/plain' });
form.append('file', blob, 'api-test.txt');
await fetch(`${PROXY_BASE}/api/files`, {
  method: 'POST',
  headers: { 'Cookie': `session_token=${token}` },
  body: form
});

const notifRes = await fetch(`${PROXY_BASE}/api/notifications`, {
  headers: { 'Cookie': `session_token=${token}` }
});
console.log('GET notifications status:', notifRes.status);
console.log('GET notifications body:', await notifRes.json());
