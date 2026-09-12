# Student Team Workspace — Project Status

> **Ngày cập nhật:** 12/09/2026 (GMT+7)
> **Trạng thái:** 🟢 W0–W10 done trên public monorepo — T-wave (audit fixes) đang landing dần qua draft PRs
> **Repo:** `skappafrost/student-team-workspace` (`stw/`), public, GitHub Flow (branch `feat/*` → draft PR → Skappa squash-merge)
> **Seeded từ:** `Team-workspace/PROJECT-STATUS.md` (03/09/2026, stale app-path era) — rewrite paths + wave state.
> **Verified on:** pytest **300 passed**, `bun run typecheck` clean, `alembic heads` = 1 (`adfcaabfb828`)

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
| T-wave | Security audit fixes T001–T050 (test-auth gate, real-JWT fixtures, bcrypt policy, role matrix, FK enforcement, …) | 🔄 Landing qua draft PRs |

Merged gần nhất trên `main` (12/09/2026): T015 duplicate-membership guard (#11), T012 private-channel membership (#8), T014 SQLite FK enforcement (#9), T040 file-delete + orphan sweeper (#7), T009 bcrypt 72-byte (#6), T002 role matrix (#5).

---

## 4. Hiện trạng kỹ thuật

```
stw/                           ← monorepo (git, branch main)
├── app/                       ← Next.js frontend
│   ├── src/app/dashboard/     ← overview, kanban, chat, calendar, wiki, files, settings
│   └── src/features/          ← chat (WS hook), calendar, projects, kanban…
├── backend/                   ← FastAPI + Alembic + Docker Compose
│   ├── app.py                 ← toàn bộ routes (auth, workspaces, channels, WS, pages, files, events, notifications, AI)
│   ├── alembic/versions/      ← head adfcaabfb828 (1 head duy nhất)
│   └── test_*.py              ← 300 tests, full suite xanh
├── README.md / RELEASE-CHECKLIST.md / PROJECT-STATUS.md (file này)
└── .github/workflows/         ← CI (đang landing qua T3-A01, chưa merge)
```

- **Stack frontend:** Next.js 16.2.12 + React 19.2.4 + TS 5.7 strict + Tailwind v4 + shadcn/ui + dnd-kit + next-themes (dark default)
- **Stack backend:** FastAPI + SQLAlchemy 2.0 + Alembic + JWT (`jose`, access 1 tuần / refresh 30 ngày, httpOnly cookie) + bcrypt
- **DB:** SQLite local default (`sqlite:///./stw.db`); PostgreSQL 16 qua Docker Compose (`postgres` + `backend` services)
- **Auth:** register / login / me / logout qua cookie; **chưa có** route `/auth/refresh` xoay vòng, **chưa có** revoke token
- **Realtime:** WS `/ws/channels/{id}` broadcast `new_message`; rooms in-memory → đúng 1 uvicorn worker
- **Dev trên PC này:** `bun run dev:webpack` bắt buộc (Turbopack gãy); LAN qua `--host 0.0.0.0` (backend) — xem README § LAN development

---

## 5. Việc tiếp theo

- [ ] Merge nốt T-wave PRs đang mở (A01 CI, A02 cleanup, …) — Skappa review + squash-merge, worker không tự merge
- [ ] T3 root-docs (task hiện tại): `README.md` + 2 file này khớp `main`
- [ ] Release local-first theo `RELEASE-CHECKLIST.md` §5
- [ ] Cloud deploy (Vercel + Neon/Supabase + Render/Fly) — để sau khi product-ready, hiện local-first

---

*Soạn bởi Vex — số liệu verify trực tiếp trên worktree (`pytest`, `typecheck`, `alembic heads`, `docker compose config`, code routes).*
