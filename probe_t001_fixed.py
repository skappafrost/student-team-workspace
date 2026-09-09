"""T001 cross-workspace RBAC probe (session-isolated).

Verifies that the cross-workspace hijack is dead:
  - user2 (member of A, admin of B) cannot PATCH/DELETE workspace A by
    passing ?workspace_id=B  -> must be 403
  - the real owner of A can PATCH it                  -> 200
  - user2 can PATCH workspace B (where they are admin) -> 200

Fix over the original probe_t001.py: use ONE session per user. The original
shared a single requests.Session, but /auth/register sets a session cookie,
so registering user2 silently re-authenticated the shared session as user2
and user2 ended up owning both workspaces (see duplicate owner+member
memberships) - the hijack assertion could never fire.

Run: python probe_t001_fixed.py  (requires backend on http://localhost:8000)
"""
import requests

BASE = "http://localhost:8000"


def register(session, email, password):
    r = session.post(f"{BASE}/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"]


def create_workspace(session, name, slug):
    r = session.post(f"{BASE}/workspaces", json={"name": name, "slug": slug})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def invite(session, ws_id, email, role="member"):
    r = session.post(f"{BASE}/workspaces/{ws_id}/invites", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def accept(session, token):
    r = session.post(f"{BASE}/invites/accept", json={"token": token})
    assert r.status_code == 201, r.text


def login(session, email, password):
    r = session.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


s1 = requests.Session()  # user1: owner of A and B
s2 = requests.Session()  # user2: member of A, admin of B

register(s1, "u1@test.com", "password123")
register(s2, "u2@test.com", "password123")

workspace_a = create_workspace(s1, "A", "a")
workspace_b = create_workspace(s1, "B", "b")

token_a = invite(s1, workspace_a, "u2@test.com", "member")
token_b = invite(s1, workspace_b, "u2@test.com", "admin")

accept(s2, token_a)
accept(s2, token_b)

# --- Hijack attempts: path=A (member role), query claims B (admin role) ---
r = s2.patch(f"{BASE}/workspaces/{workspace_a}?workspace_id={workspace_b}", json={"name": "HIJACKED"})
print("PATCH A?workspace_id=B status:", r.status_code)
assert r.status_code == 403, f"Expected 403, got {r.status_code} ({r.text})"

r = s2.delete(f"{BASE}/workspaces/{workspace_a}?workspace_id={workspace_b}")
print("DELETE A?workspace_id=B status:", r.status_code)
assert r.status_code == 403, f"Expected 403, got {r.status_code}"

# --- Legit owner operations must still work ---
r = s1.patch(f"{BASE}/workspaces/{workspace_a}", json={"name": "A-updated"})
print("PATCH A by owner status:", r.status_code)
assert r.status_code == 200, r.text

# --- Legit admin operation in B must still work ---
r = s2.patch(f"{BASE}/workspaces/{workspace_b}", json={"name": "B-updated"})
print("PATCH B by admin status:", r.status_code)
assert r.status_code == 200, r.text

# Cleanup: owner deletes both workspaces
s1.delete(f"{BASE}/workspaces/{workspace_a}")
s1.delete(f"{BASE}/workspaces/{workspace_b}")

print("All probe checks passed.")
