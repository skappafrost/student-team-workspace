# Student Team Workspace — Project Status

> **Ngày cập nhật:** 19/09/2026 (GMT+7)
> **Trạng thái:** 🟢 W0–W10 + UI redesign + toàn bộ T-wave/TA-wave (hardening) đã merge trên `main`; đang chạy S-wave (realtime presence)
> **Repo:** `skappafrost/student-team-workspace`, public, GitHub Flow (`feat/*` + `harden/*` branches → draft PR → Skappa squash-merge)
> **Verified on:** `pytest -q` **757 passed** (SQLite, `backend/.venv`) · `alembic heads` = 1 (`prs01_presence_state`) · coverage **91%** với floor `fail_under = 90` (`backend/pyproject.toml:50`) · CI **4 jobs** (`backend`, `backend-pg`, `frontend`, `demo-pack`) — tất cả số này đo trực tiếp trên `main` @ `40ada4d` ngày 19/09; chạy lại lệnh trước khi quote.

---

## 1. Dự án này là gì?

**Student Team Workspace (STW)** — không gian làm việc số thống nhất cho nhóm học sinh, gộp tinh túy của Notion (wiki), Discord (chat), Trello (kanban), Drive (files) và một lớp AI hiểu ngữ cảnh.

**Nguyên tắc cốt lõi:** mọi thứ nối với nhau qua context chung — task liên kết chat, tài liệu, deadline; AI đọc được toàn bộ workspace.

**Tài liệu gốc (nằm ngoài repo, ở `Team-workspace/`):**
- `IDEA.md` — ý tưởng 1 đoạn
- `student_workspace_ecosystem.md` — spec đầy đủ (kiến trúc, data model, roadmap 5 phase)
- `design-references/catalogs/DECISIONS.md` — 8 quyết định design đã khóa
- `SESSION-CONTEXT.md` — handoff cũ (stale paths, chỉ tham khảo lịch sử)

---

## 2. Design direction đã khóa

Từ notes của anh trên gallery (`design-reference-my-notes.json`, 51 favorites / 29 notes):

| # | Quyết định | Nguồn cảm hứng |
|---|---|---|
| D1 | Linear-dark aesthetic — nền tối phân tầng, viền 1px sắc | Linear ("ABSOLUTELY CINEMA"), Reflect |
| D2 | Scaffold gốc: `next-shadcn-dashboard-starter` (Kiranism) | "THIS ONE IS SO GOODDD!!!!" |
| D3 | Compact density — dashboard dạng cockpit | Focalboard, ngx-admin cluster |
| D4 | Dark mặc định + light đầy đủ | Notes nhắc dark mode 3 lần |
| D5 | Component base: shadcn/ui + Origin UI + Tremor | Origin UI "SOO GOOOD!!!" |
| D6 | Motion ngắn 150–250ms, mượt không lòe loẹt | AFFiNE, Tokyo dashboard |
| D7 | Bản đồ cảm hứng theo từng màn hình (kanban, wiki, chat...) | Toàn bộ favorites |
| D8 | Cổng verify: Checklist Design + pool Godly/Dribbble trước khi ship | Chính notes của anh |

**Luật sắt:** zero native design — mọi UI phải truy vết được về một reference. Không tự chế bất cứ thứ gì.

---

## 3. Những gì đã xong

| Wave | Nội dung | Trạng thái |
|---|---|---|
| W0 | Design decisions + tooling | ✅ Done |
| W1 | App shell & theme (dark default, sidebar Linear 7 mục, motion D6) | ✅ Done |
| W2 | FastAPI + Postgres schema, JWT auth, workspace/members, route guard | ✅ Done |
| W3 | Projects + Kanban (dnd-kit, task detail), QA gate 12/12 E2E | ✅ Done |
| W4 | Calendar API + UI, dialog hydration fix, kanban proxy fix | ✅ Done |
| W5 | Chat channels/messages API + UI, WebSocket broadcast, QA gate | ✅ Done |
| W6 | Wiki (page tree, editor/viewer, search) | ✅ Done |
| W7 | Files (upload/list) + notifications/activity | ✅ Done |
| W8 | AI layer (summarize, search) | ✅ Done |
| W9 | Chat polish (author display name, create-channel UI) | ✅ Done |
| W10 | QA fixes + local run docs + release checklist | ✅ Done |
| Redesign | UI reskin: teamspace theme, real overview dashboard, kanban loop fix (+F01–F03, R01, D01) — PR #28 | ✅ Merged 14/09/2026 |
| T-wave | Security audit fixes T001–T050 (RBAC role matrix, FK enforcement, bcrypt policy, private channels, orphan sweeper, rate limiting, Postgres CI…) | ✅ Đã merge hết (squash #1 → #175) |
| TA-wave | Backend contract hardening: auth refresh lifecycle, upload ingress/egress, storage quota, pagination contract, notification fan-out, WS auth, N+1 + indexes, dialect parity, ops maintenance, observability, load baseline, coverage floor, security regression pack | ✅ Done (Task A, #123–#175) |
| Recovery | Sửa các wiring mà squash-merge làm rơi ở #123/#126/#130/#148/#159/#161/#163 + bỏ `except Exception: pass` trong `conftest.py` từng che hỏng hóc | ✅ #185, #188 |
| S-wave | Realtime presence: S3 single-head, S4 `PresenceState` model, S5 service + HTTP set/list + WS fan-out, **S6 presence UI (frontend)** | 🔄 S3–S5 đã merge (#188, #189); **S6 chưa làm** |

**Merged trên `main` (mới nhất trước):** #189 presence service + WS (S5) · #188 Alembic single-head + `PresenceState` (S3/S4) · #185 restore baseline · #175 security regression pack (TA7-1) · #174 coverage floor + RBAC edge tests (TA6-3) · #164 load/perf baseline (TA6-2) · #163 ops maintenance (TA5-3) · #162 SQLite/PG dialect parity (TA5-2) · #161 WS auth + semantics (TA4-2) · #160 docs rewrite (TA3-3) · #159 pagination contract (TA3-1) · #149 observability + `/readyz` (TA6-1) · #148 N+1 + indexes (TA5-1) · #138 notification fan-out (TA4-1) · #134 LIKE escape + channel type enum (TA3-2) · #132 storage quota (TA2-3) · #130 authenticated `/uploads` read (TA2-2) · #128 upload ingress (TA2-1) · #126 jti request-scoped session (TA1-3) · #124 JWT secret governance (TA1-2) · #123 `/auth/refresh` (TA1-1) · #102 kanban guard · #101/#100/#99 rate-limit fallback + app README + demo-pack CI · #88 Postgres CI · #87 manage.py tests · #80 lifespan · #79 request log + healthz · #78 rate limiting · #28 UI redesign · Dependabot #81–#86.

> ⚠️ **Caveat khi verify bằng `git log`:** repo merge theo kiểu squash, nên **commit hash ≠ merge commit của PR**. Muốn biết PR nào đã landing, dùng `gh pr view <N> --json number,state,mergeCommit` — đừng kết luận từ `git log --oneline`. Chính hiểu nhầm này làm tài liệu cũ ghi sai trạng thái #123–#159 là "đang mở" cả tuần sau khi chúng đã merge.

**Test baseline hiện tại:** `cd backend && .venv/Scripts/python -m pytest -q` → **757 passed** (SQLite) trên `main` @ `40ada4d`, 55 file test. Số này thay đổi theo từng PR — luôn chạy lại lệnh, hoặc tốt hơn là link thẳng tới CI badge thay vì chép số vào doc.

---

## 4. Hiện trạng kỹ thuật

```
stw/                           ← monorepo (git, branch main @ 40ada4d)
├── app/                       ← Next.js 16 frontend
│   ├── src/app/dashboard/     ← overview, kanban, chat, calendar, wiki, files, settings
│   ├── src/app/api/          ← BFF route handlers (proxy session cookie → backend)
│   └── src/features/         ← chat (WS hook), calendar, projects, kanban…
├── backend/                   ← FastAPI + Alembic + Docker Compose
│   ├── routers/              ← 15 domain routers (thêm presence), 51 HTTP paths + 2 WS routes
│   ├── alembic/versions/     ← head prs01_presence_state (1 head duy nhất)
│   └── test_*.py             ← 757 tests / 55 files, full suite xanh (SQLite + Postgres)
├── docs/API.md               ← endpoint map + realtime + BFF map + changelog
├── docs/OPS.md               ← backup / retention / verification
├── docs/PERF-BASELINE.md     ← benchmark + load evidence
├── CONTRIBUTING.md           ← branch/PR flow, checks, conventions
├── README.md / RELEASE-CHECKLIST.md / PROJECT-STATUS.md (file này)
├── Makefile                  ← make dev / make test
├── scripts/demo-packs/       ← busy-workspace.json + load/make pack scripts
└── .github/workflows/ci.yml  ← CI 4 jobs: backend, backend-pg, frontend, demo-pack
```

- **Stack frontend:** Next.js 16.3.5 + React 19.2.4 + TS 5.7.2 strict + Tailwind v4 (CSS-first, không có `tailwind.config.*`) + shadcn/ui **trên Base UI (không phải Radix)** — dùng `render={<Button/>}` thay vì `asChild` — + dnd-kit + TanStack Query 5 + next-themes (dark default)
- **Stack backend:** FastAPI + SQLAlchemy 2.0 + Alembic + JWT (`jose`, access 1 tuần / refresh 7 ngày, httpOnly cookie) + bcrypt
- **DB:** SQLite local default (`sqlite:///./stw.db`); PostgreSQL 16 qua Docker Compose (`postgres` + `backend` services, bắt buộc `backend/.env`)
- **Auth:** register / login / me / logout / logout-all / **refresh** qua cookie + session revocation theo `jti`. `/auth/refresh` đã merge (#123, commit `6031e41`): refresh token single-use, mỗi lần rotate mint row kế tiếp trong cùng `family_id`; replay token đã rotate = thu hồi **cả family** + `401`. Startup từ chối default secret ngoài dev/test (#124).
- **Realtime:** 2 socket — `/ws/channels/{id}` (rooms `chan:` + `user:`) và `/ws/workspaces/{id}/presence` (room `workspace:`), chung một handshake resolver và bảng close code 4401/4403/4404. Ba room namespace rời nhau: `presence_update` không sang chat socket, `notification_created` không sang presence socket. **Rooms + presence refcount đều là in-memory → chỉ đúng với 1 uvicorn worker**; scale ngang cần shared store. Presence: `online` ghi ở socket *đầu tiên*, `offline` chỉ ở socket *cuối cùng*; read-time decay `online`→`away` (300s) và →`offline` (1800s), không có scheduler hay TTL column.
- **Rate limiting:** login/register/upload/ai có bucket riêng, các write route khác có fallback cap; trả `429` + `Retry-After`
- **Dev trên PC này:** `bun run dev:webpack` bắt buộc (Turbopack gãy); LAN qua `--host 0.0.0.0` (backend) — xem README § LAN development

---

## 5. PRs đang mở (19/09/2026)

Lấy từ `gh pr list --repo skappafrost/student-team-workspace --state open` — **17 PR**. Chạy lại lệnh trước khi quote; đừng tin bảng này sau vài ngày.

| PR | Branch / loại | Nội dung | Hành động |
|---|---|---|---|
| #176–#184 | `feature/T00x-…` (9 PR) | **Vòng rehash cũ** của T001, T002, T003, T004, T009, T012, T014, T015, T040 — các hành vi này đã landing từ lâu (#1–#11 và TA-wave). | Đối chiếu từng cái với danh sách merged ở §3 rồi **close không merge** |
| #121 | `feature/T020-…` | T020 — search correctness/privacy trên pages | Đã có TA3-2 (LIKE escape); review xem còn phần nào thiếu |
| #137 | `feat/notifications-v2` | Client notifications v2 (Bell đọc từ mock Zustand store, chưa nối `/api/notifications` thật) | Quyết định: merge sau S-wave hay đóng |
| #85 | Dependabot `@shadcn/react` 0.2.1 → 0.3.1 | Minor, rủi ro API thấp | Giữ, cần smoke test |
| #190–#192 | Dependabot backend | fastapi `>=0.112→0.141`, httpx `0.27→0.28`, uvicorn `0.30→0.53` | Bump thường, chạy full suite |
| #193 | Dependabot `typescript` 5.7.2 → **7.0.2** | **MAJOR** | Không merge dồn với PR khác; cần `bun run typecheck` + build |
| #194 | Dependabot `@tanstack/react-table` 8 → **9** | **MAJOR** | Như trên |

---

## 6. Việc tiếp theo

**Product**
- [ ] **S6 — presence UI (frontend)**, branch `feat/rt-presence-ui`: consume `GET /workspaces/{id}/presence` + `/ws/workspaces/{id}/presence`, dot trên DM list / member table / user menu. **Phải theo Zero Native Design Rule** — mọi visual truy vết về một reference trong `design-references/` (catalog hiện **chưa có** entry presence nào, và cũng chưa có field nào ghi lại "adaptation" — phải tạo trước khi code).
- [ ] Quyết định mở: `POST /presence/me` ghi `Activity` row (`verb=set_presence`) — status spam có nên nằm trong activity feed + audit log không?

**Kỹ thuật còn nợ**
- [ ] `manage.py create-user` **chạy được trên DB trống**: hiện query `users` ở `backend/manage.py:227` nhưng chỉ gọi `create_all` ở `:231`, nên lần chạy đầu tiên trên DB mới toang với `no such table: users`. Cần quyết định lệnh nào sở hữu schema creation.
- [ ] `POST /api/notifications` action `mark-all-read` đang proxy tới `POST /notifications/mark-all-read` — **route backend không tồn tại**, handler hiện trả 405. Hoặc thêm route, hoặc bỏ handler.
- [ ] `app/src/features/workspace/components/workspace-settings-page.tsx:31` liệt kê roles `owner|admin|member|**viewer**` trong khi backend chỉ có `owner|admin|member|**guest**` (`authorization.py:17`). Dropdown cho phép chọn "viewer" — role không tồn tại ở server.
- [ ] Chuông notification (`app/src/features/notifications/utils/store.ts:105`) vẫn đọc `mockNotifications` tại `:23`, chưa nối `GET /api/notifications` thật.
- [ ] CI gate `ruff check` (PR `harden/ruff-debt-and-gate`): hết debt, thêm job thứ 5. `ruff format` **không** gate (69 file / ~1945 dòng chưa sạch).
- [ ] `app/.env.local` để `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` trong khi CONTRIBUTING bắt dùng `localhost`: `session_token` là `SameSite=Lax` nên khác hostname = cookie không gửi lên WS upgrade → **mọi handshake chat + presence 4401 trước `accept()`**. Cần guard phía client báo rõ lỗi thay vì retry im lặng.
- [ ] Frontend CI hiện chỉ `typecheck` — không lint, không build, không test; Playwright có devDep nhưng 2 spec và không chạy trong CI.

**Release**
- [ ] Giải nốt #85 sau khi có smoke test; triage #193/#194 (major) riêng.
- [ ] Release local-first theo `RELEASE-CHECKLIST.md` §5
- [ ] Cloud deploy (Vercel + Neon/Supabase + Render/Fly) — để sau; lưu ý realtime là in-memory nên **1 worker duy nhất** cho tới khi có shared room store.

---

*Soạn bởi Vex — số liệu verify trực tiếp trên repo ngày 19/09/2026: `pytest -q` / `--collect-only`, `alembic heads`, `coverage report`, `gh pr list --state open`, route walk từ `app.routes`, và `git log`/`gh pr view` cho trạng thái merge.*
