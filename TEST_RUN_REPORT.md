# T002 Role-Matrix Regression Tests — Completion Report

**Task:** `t_eab80d37` (T002 role-matrix regression tests)
**Branch:** `feature/T002-role-matrix-regression-tests-for`
**Date:** 2026-09-09 (SE Asia Standard Time, UTC+07:00)
**Status:** COMPLETED — 253 tests passing (152 baseline + 101 new T002 tests)

## What was done

### 1. T001 fix applied (hard dependency)
This worktree's `backend/app.py` was still the vulnerable pre-T001 version (T001's
fix existed only as uncommitted changes in its own worktree). Applied T001's exact
fix: `require_role()`/`require_permission()` no longer accept a query-param
`workspace_id`; all 11 privileged workspace-scoped handlers now call
`_require_min_role_in_workspace(path_workspace_id, ...)` as their first statement,
so the membership/role check is scoped to the *path* workspace only.

Also applied the t_fe08c490 404-ordering correction (spec from that triage task's
body: `_get_workspace_or_404` BEFORE the role check in every handler). Without it,
two pre-existing tests (`test_delete_nonexistent_workspace_returns_404`,
`TestEdgeCases::test_nonexistent_workspace_returns_404`) fail because a
nonexistent workspace would 403 instead of 404. With it, the full suite stays
green. Note: that triage task's worker was blocked without its spec; the fix is
implemented here per the spec and its branch (`fix/T001-404-ordering`) is now
redundant.

### 2. New regression tests (backend/test_role_matrix.py, +475 lines)
Three new classes, all using REAL JWT auth (`Authorization: Bearer
<create_access_token(user_id)>`) — no X-Test-User-* header bypass:

- **TestT002CrossTenantMatrix** (72 parametrized cases): the 12 privileged
  endpoints from T001 × 6 actors (owner / admin / member / guest of target ws-A,
  stranger who is member of other-workspace ws-B only, anonymous). Asserts the
  exact status code per cell AND, for forbidden writes, re-GETs as owner to prove
  no side effect (state snapshot before/after must match).
- **TestT002QueryPathMismatch** (25 cases): the T001 regression class. For each
  path-scoped endpoint, an attacker who is owner/member of ws-B sends the request
  targeting ws-A in the path with `?workspace_id={ws_b}` — must get 403 and leave
  no side effect. Also covers duplicate params
  (`?workspace_id={ws_b}&workspace_id={ws_a}`, FastAPI binds the first) and the
  matching-query no-behavior-change case.
- **TestT002ChannelWebsocket** (4 cases): `/ws/channels/{id}` membership check —
  member connects (pong), guest/member-of-other-workspace/anonymous rejected.

New parametrized case count: 72 + 22 = 94 parametrized + 7 non-parametrized =
101 new tests (requirement: ≥60 new parametrized cases; 12 endpoints × ≥5 actors).

### 3. Mutation check (acceptance criterion)
Temporarily reverted T001's fix and re-ran the matrix:

- Naive revert (HEAD app.py) is *observationally equivalent* under FastAPI
  0.141.1: a plain `workspace_id: str = None` parameter in a dependency binds to
  the PATH param when the route has `{workspace_id}`, so the query value is
  ignored and the old code also 403s. Verified with an instrumented probe
  (`require_role` received the path workspace id).
- The bug class still exists if the dependency is made to read the query value
  (T001's actual concern). Reintroduced that (dependency reads `workspace_id`
  from the query string via `Query(alias=...)`): **the matrix went RED — 12
  failures**, exactly the cross-tenant escalation T001 fixed (owner of ws-B could
  rename/delete ws-A, stranger could create projects in ws-A). Restored the fix;
  all 130 tests in the file green again.

Conclusion: the matrix locks the path-scoped contract and catches the T001 bug
class if it is reintroduced.

## Verification (all real, this session)
- `pytest test_role_matrix.py` → 130 passed (29 pre-existing + 101 new)
- Full backend suite `pytest -q` → **253 passed, 4 warnings** (baseline 152 +
  101 new), run twice (before/after mutation check)
- `pytest --collect-only` → 253 tests collected (was 152)

## Files changed
- `backend/app.py` — T001 fix + 404-ordering correction (the task's hard
  dependency; T001's own branch never committed it)
- `backend/test_role_matrix.py` — +475 lines: T002 matrix, mismatch class, WS
  membership tests
- `TEST_RUN_REPORT.md` — this report (replaces the earlier blocked report)

## Notes for the orchestrator
- T001's fix was never committed anywhere (it lived uncommitted in worktree
  `t_d35515fc`). It is committed here as part of this branch so the dependency is
  durable. Recommend merging this branch and closing t_fe08c490 as redundant.
- The unused `Path` import in `app.py` line 9 comes from T001's diff; harmless,
  left untouched to keep the diff identical to T001's validated work.
