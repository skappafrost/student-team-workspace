# Student Team Workspace — Project Status

> **Ngày cập nhật:** 16/09/2026 (GMT+7)
> **Trạng thái:** 🟢 W0–W10 + UI redesign đã ship trên `main` — T-wave (audit fixes) đang landing dần qua draft PRs `harden/*`
> **Repo:** `skappafrost/student-team-workspace`, public, GitHub Flow (`feat/*` + `harden/*` branches → draft PR → Skappa squash-merge)
> **Verified on:** pytest **408 passed** (SQLite), `alembic heads` = 1 (`m3rge_task2_heads`), CI 4/4 jobs (`backend`, `backend-pg`, `frontend`, `demo-pack`)

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
| T-wave | Security audit fixes T001–T050 (RBAC role matrix, FK enforcement, bcrypt policy, private channels, orphan sweeper, rate limiting, Postgres CI…) | 🔄 Landing qua draft PRs `harden/*` |

**Merged trên `main` (mới nhất trước):** PR #28 UI redesign (bca27ce), Dependabot #81–#84 + #86 (pydantic, zustand, tabler/icons, requests, email-validator), PR #102 kanban empty-projectId guard, #100 app README, #101 fallback rate limit, #99 demo-pack CI, #88 Postgres CI job, #87 manage.py tests, #80 lifespan handler, #79 request logging + healthz, #78 rate limiting.

**Test baseline hiện tại:** 408 passed (SQLite, `backend/.venv`, main @ bca27ce). Số này tăng khi các PR `harden/*` merge — chạy lại trước khi quote.

---

## 4. Hiện trạng kỹ thuật

```
stw/                           ← monorepo (git, branch main @ bca27ce)
├── app/                       ← Next.js 16 frontend
│   ├── src/app/dashboard/     ← overview, kanban, chat, calendar, wiki, files, settings
│   ├── src/app/api/          ← BFF route handlers (proxy session cookie → backend)
│   └── src/features/         ← chat (WS hook), calendar, projects, kanban…
├── backend/                   ← FastAPI + Alembic + Docker Compose
│   ├── routers/              ← 14 domain routers, 45 paths tổng cộng
│   ├── alembic/versions/     ← head m3rge_task2_heads (1 head duy nhất)
│   └── test_*.py             ← 408 tests, full suite xanh (SQLite + Postgres)
├── docs/API.md               ← endpoint map + BFF map + changelog
├── CONTRIBUTING.md           ← branch/PR flow, checks, conventions
├── README.md / RELEASE-CHECKLIST.md / PROJECT-STATUS.md (file này)
├── Makefile                  ← make dev / make test
├── scripts/demo-packs/       ← busy-workspace.json + load/make pack scripts
└── .github/workflows/ci.yml  ← CI 4 jobs: backend, backend-pg, frontend, demo-pack
```

- **Stack frontend:** Next.js 16.2.12 + React 19.2.4 + TS 5.7 strict + Tailwind v4 + shadcn/ui + dnd-kit + next-themes (dark default)
- **Stack backend:** FastAPI + SQLAlchemy 2.0 + Alembic + JWT (`jose`, access 1 tuần / refresh 7 ngày, httpOnly cookie) + bcrypt
- **DB:** SQLite local default (`sqlite:///./stw.db`); PostgreSQL 16 qua Docker Compose (`postgres` + `backend` services, bắt buộc `backend/.env`)
- **Auth:** register / login / me / logout / logout-all qua cookie + session revocation theo `jti`; `/auth/refresh` đang ở PR #123 (chưa merge)
- **Realtime:** WS `/ws/channels/{id}` broadcast `new_message` + typing; rooms in-memory → đúng 1 uvicorn worker
- **Rate limiting:** login/register/upload/ai có bucket riêng, các write route khác có fallback cap; trả `429` + `Retry-After`
- **Dev trên PC này:** `bun run dev:webpack` bắt buộc (Turbopack gãy); LAN qua `--host 0.0.0.0` (backend) — xem README § LAN development

---

## 5. PRs đang mở (16/09/2026)

| PR | Branch | Nội dung |
|---|---|---|
| #159 | `harden/pagination-contract` | Uniform `limit`/`offset` trên list endpoints (TA3-1) |
| #150–#158 | `feature/T00x-…` | **Stale rehash rounds** of T001–T040, which already landed in #1–#11 (T001 #3, T002 #5, T003 #1/#4, T004 #2, T009 #6, T012 #8, T014 #9, T015 #11, T040 #7). Closed/rejected rounds; safe to close without merge — verify with `git log origin/main --grep=T0xx`. |
| #149 | `harden/observability` | Slow-query log, 5xx counter, /readyz (TA6-1) |
| #148 | `harden/nplus1-indexes` | N+1 elimination + FK index plan (TA5-1) |
| #138 | `harden/message-fanout` | Notification fan-out on message create (TA4-1) |
| #137 | `feat/notifications-v2` | Client-side notifications v2 program |
| #134 | `harden/like-escape-channels-enum` | LIKE wildcard escape + channel type enum (TA3-2) |
| #132 | `harden/storage-quota` | Per-workspace storage quota (TA2-3) |
| #130 | `harden/uploads-read-auth` | Authenticated /uploads read path |
| #128 | `harden/upload-ingress` | Upload sanitize, size cap, allow-list (TA2-1) |
| #126 | `harden/jti-request-session` | jti revocation qua request DB session (TA1-3) |
| #124 | `harden/jwt-secret-governance` | Refuse default JWT secret ngoài dev/test (TA1-2) |
| #123 | `harden/auth-refresh` | POST /auth/refresh rotation (TA1-1) |
| #85 | `dependabot/bun/app/shadcn/react-0.3.1` | @shadcn/react 0.2.1 → 0.3.1 (đang giữ, rủi ro API nhỏ) |

---

## 6. Việc tiếp theo

- [ ] Skappa review + squash-merge các PR `harden/*` đang mở (worker không tự merge)
- [ ] Sau khi merge: cập nhật `docs/API.md` § Changelog (chuyển dòng từ "open" sang "landed") + chạy lại pytest để lấy số mới
- [ ] Giải nốt #85 (@shadcn/react 0.3.1) sau khi có smoke test
- [ ] Release local-first theo `RELEASE-CHECKLIST.md` §5
- [ ] Cloud deploy (Vercel + Neon/Supabase + Render/Fly) — để sau khi product-ready, hiện local-first

---

*Soạn bởi Vex — số liệu verify trực tiếp trên repo (`pytest`, `alembic heads`, `gh pr list`, OpenAPI spec, code routes) ngày 16/09/2026.*
