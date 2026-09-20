# Student Team Workspace — Project Status

> **Ngày cập nhật:** 20/09/2026 (GMT+7)
> **Trạng thái:** 🧊 **BẢO TRÌ — đóng băng từ 2026-09-20.** Ảnh chụp `main` ở `9105cdc` (kế hoạch realtime 9 PR đã chạy xong, #212–#220). Đọc §0 trước khi làm bất cứ việc gì.
> **Repo:** `skappafrost/student-team-workspace`, public, GitHub Flow (`feat/*` + `harden/*` branches → draft PR → Skappa squash-merge)
> **Verified on:** `cd backend && .venv/Scripts/python -m pytest -q` → **810 passed / 60 file** (SQLite; `test_manage.py::test_seed_demo_fresh_recreates_sqlite_file` vẫn là flake Windows tmp-file-lock đã biết — lần chạy này không tái hiện, xanh trên CI Linux) · `--cov` → coverage **91.98%** với floor `fail_under = 90` (`backend/pyproject.toml:50`) · `alembic heads` = 1 (`prs01_presence_state`) · `cd app && bunx playwright test --workers=1` → **37 passed / 10 spec file** · CI **6 jobs** (`ruff`, `backend`, `backend-pg`, `frontend`, `frontend-e2e`, `demo-pack`) — đo ngày 20/09/2026 trên `main` @ `9105cdc` (CI của PR cũng chạy đúng các lệnh đó trên Linux, nên mỗi số đo có hai lần xác nhận; `workers=1` vì 4 worker làm Next dev server crash — số đo 4/2/1 ghi trong `app/playwright.config.ts`). Chạy lại lệnh trước khi quote.

---

## 0. Đóng băng để bảo trì (từ 2026-09-20)

Repo ngừng nhận thay đổi cho tới khi có lệnh mở lại. Phần này là **ảnh chụp tại thời điểm dừng**, không phải kế hoạch đang chạy — mỗi mục đều kèm lệnh chạy lại để kiểm chứng, vì số liệu trong doc này cũ rất nhanh.

**Ảnh chụp `main`:** `9105cdc` = #220, item cuối của kế hoạch sửa realtime 9 PR (#212–#220, mỗi cái một PR, đều squash-merge, CI 6/6 xanh). Không còn PR nào mở của riêng wave này, không có worktree nào sống, working tree sạch.

**17 PR đang mở — đóng băng tại chỗ bằng `gh pr lock`, giữ nguyên branch và nội dung**, không merge, không đóng, không rebase: #85, #121, #137, #176–#184, #190–#194 (nội dung từng cái ở bảng §5). Mở khoá khi nối lại:

```
gh pr list --state open --json number --jq '.[].number' | xargs -n1 gh pr unlock
```

Hệ quả phụ phải biết: PR bị lock thì author không push thêm được, nên Dependabot không update nổi #85/#190–#194; nếu nó tự đóng PR vì bị lock, branch vẫn còn trên remote và chạy lại workflow là lấy lại được. #176–#184 là vòng rehash của những hành vi đã landing từ #1–#175 — đối chiếu danh sách merged ở §3 trước khi quyết định, đừng merge.

**Việc dở dang** (mô tả đầy đủ ở §6; cột cuối là lý do dừng, để người mở lại không phải đoán lại từ đầu):

| # | Việc | Dừng ở đâu |
|---|---|---|
| 12 | S6 UI còn nợ: roster sắp theo presence, dot trong dialog New DM, chữ "N online" ở overview | Chưa làm vì *luật*, không vì kỹ thuật: 2/3 bề mặt chưa có record trong `app/design-references/catalogs/usages.json`, mà `AGENTS.md` bắt tìm nguồn + chép catalog trước khi thi công. Bẫy riêng: `onlineCount` đã bị bỏ khỏi presence context trong #219, nên hoặc tính từ `byUser`, hoặc đưa field về kèm test chứng minh có consumer |
| 32 | `alembic` và app trỏ hai DB khác nhau (`alembic.ini` = Postgres, app default = `sqlite:///./stw.db`) | Nguyên nhân và đường sửa đã rõ (fallback `settings.database_url` trong `alembic/env.py`, truyền `DATABASE_URL` vào webServer của `app/playwright.config.ts`, ghi chú rằng `create_all` không thêm cột vào bảng có sẵn). Chưa làm vì ngoài phạm vi wave realtime |
| 33 | Đưa WS fan-out khỏi request path của POST, **giữ thứ tự** | Hai hình thái đã bị loại kèm số đo: `asyncio.gather` (park receiver — xem docstring `ws._ws_broadcast`) và `create_task` cho từng message (frame sau vượt frame trước, còn `chat-page.tsx` append theo thứ tự nhận). Hình đúng là hàng đợi theo room với một task drain mỗi room; phần khó nhất là **loop affinity**, vì mỗi TestClient portal có event loop riêng |
| 34 | Hai hình thái của một socket bị từ chối (403 rỗng vs 403 + `{"detail":…}`) | Không phải bug với client (không mã close nào sống sót cả) nên mới chỉ được ghi vào docs. Đường thống nhất nếu cần: bắt `HTTPException` ở `channels.py:channel_websocket` giống `presence.py` đã làm |
| 35 | Trần connection pool: `QueuePool(5 + 10)` → 20 request đồng thời thì 5 cái 500 sau **151.5 s**, kèm `Cannot operate on a closed database` khi rollback | Phát hiện tình cờ khi đo cho #220. Chưa sửa vì cần quyết định cấu hình (nâng pool, hay đừng giữ connection suốt request, hay `pool_timeout`, và Postgres trong `docker-compose.yml` cho phép bao nhiêu). Repro: `cd backend && .venv/Scripts/python bench/loop_blocking_probe.py 20` |

**Số đo hiệu năng trong doc này là máy Windows cục bộ.** bcrypt 264–352 ms, loop gap 4904 ms… là của một laptop cụ thể; CI không chạy probe nên không có lần đo thứ hai. Cái đáng tin là **tỉ lệ trước/sau** và lệnh chạy lại, không phải con số tuyệt đối.

**Flake đã biết — đừng đi săn lại:**
- `test_manage.py::test_seed_demo_fresh_recreates_sqlite_file` → `PermissionError` khoá file tmp trên Windows; xanh khi chạy lẻ và xanh trên CI Linux.
- `realtime-delivery.spec.ts` (mục edit/delete) fail **một lần** trong khoảng sáu lần chạy đầy đủ, kèm dev overlay `Runtime SyntaxError: Unexpected end of JSON input` và dòng `ConnectionResetError: [WinError 10054]` trong log webServer. Chạy lẻ 1 spec: pass 9.2 s; chạy lại cả suite: 37/37. Triệu chứng thuộc dev server + backend trên loopback Windows, không phải sản phẩm.

**Bẫy harness đã tốn thời gian, ghi lại để không phải trả lần nữa:**
1. `TestClient` chạy **mỗi** websocket session trên **một portal event loop riêng**. Bất kỳ thứ gì làm trì hoãn send sang socket khác (`gather`, thread hop trước `_publish`, `create_task`) đều có thể park receiver vĩnh viễn — test sẽ **treo**, không fail.
2. `receive_json()` không có timeout. Đọc socket trong test thì dùng `conftest.drain_until_reply(session)` (gửi `ping`, trả về các frame trước `pong`): bao giờ cũng fail thay vì treo.
3. Playwright `workers=1`: 4 worker làm Next dev server crash (`RangeError: Array buffer allocation failed`) và 11 fail dây chuyền trông như hỏng thật.
4. `-p no:logging` làm `caplog` biến mất (9 test "error" oan). `alembic` gọi `fileConfig()` và thay root handler → mọi assertion `caplog` sau đó hỏng, nên `test_models.py::_alembic()` snapshot/restore handler.
5. Chạy e2e ghi đè PNG trong `app/qa-evidence/`; nhớ `git checkout -- app/qa-evidence/` trước khi commit.

**Artifact chỉ có trên máy này, git không mang theo** (đã gitignore): `backend/stw.stale-20260920.db` — DB dev cũ được xoay sang tên này vì thiếu cột `notifications.link` (chính là #32); `backend/stw.db` hiện tại; `backend/probe_ta32.db`; 27 file `backend/test_stw*.db` (mỗi test module tự đặt `DATABASE_URL` riêng, và một số để lại file sau khi chạy); `app/.next/`, `app/playwright-report/`, `app/test-results/`. Muốn lấy lại DB dev cũ: dừng app, `mv backend/stw.db backend/stw.broken.db && mv backend/stw.stale-20260920.db backend/stw.db`, rồi migrate hoặc để `create_all` dựng lại.

**Nối lại:** đọc §6 theo thứ tự bảng ở trên → `git pull --ff-only origin main` → `gh pr list --state open` (danh sách có thể đã đổi) → chạy `cd backend && .venv/Scripts/python -m pytest -q` và `cd app && bunx playwright test --workers=1` để lấy số hiện tại → mở khoá các PR.

---

## 1. Dự án này là gì?

**Student Team Workspace (STW)** — không gian làm việc số thống nhất cho nhóm học sinh, gộp tinh túy của Notion (wiki), Discord (chat), Trello (kanban), Drive (files) và một lớp AI hiểu ngữ cảnh.

**Nguyên tắc cốt lõi:** mọi thứ nối với nhau qua context chung — task liên kết chat, tài liệu, deadline; AI đọc được toàn bộ workspace.

**Tài liệu gốc (nằm ngoài repo, ở `Team-workspace/`):**
- `IDEA.md` — ý tưởng 1 đoạn
- `student_workspace_ecosystem.md` — spec đầy đủ (kiến trúc, data model, roadmap 5 phase)
- `design-references/catalogs/DECISIONS.md` — 8 quyết định design đã khóa (sống ngoài repo, trong `Team-workspace/`). Ledger adaptation thì **không**: `app/design-references/catalogs/usages.json` đã được copy vào repo cùng wave này để reviewer đọc được trong cùng diff với code nó audit.
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
| W3 | Projects + Kanban (dnd-kit, task detail), script QA `e2e-w3-projects-kanban.mjs` 12/12 | ✅ Done — ⚠️ đó là **transcript chạy tay**, không phải gate: script này không có exit code cho tới #208 |
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
| S-wave | Realtime presence: S3 single-head, S4 `PresenceState` model, S5 service + HTTP set/list + WS fan-out, **S6 presence UI (frontend)**, S6-RT1…RT9 sửa defect realtime | ✅ S3–S5 (#188, #189) · S6 UI (#210, #211) · vòng realtime (#212–#220) — còn lại là phần nợ ghi ở §6 |

**Merged trên `main` (mới nhất trước):** #220 bcrypt rời khỏi event loop — `run_in_threadpool` ở register/login/delete-account, đo 12 register đồng thời: loop bị bỏ rơi 4904ms → 110–211ms (S6-RT5) · #219 chat cache + lifecycle hygiene (`reaction_update` có `channel_id`, dọn typing state khi đổi channel, optimistic row settle theo id của chính nó) · #218 sự thật về một handshake bị từ chối (docs + test ở tầng ASGI) · #217 tab chat reconnect thì refetch và tự báo "đang kết nối lại" · #216 frame `message_updated` / `message_deleted` lan vào room (kèm cả subtree bị CASCADE) · #215 fan-out có bound `WS_SEND_TIMEOUT_SECONDS` — một peer treo không còn giữ cả room · #214 presence frame contract: heartbeat chỉ reset `last_seen`, status sai trả `presence_error` · #213 `notification_created` thực sự tới socket (trước đó luôn là 0 frame) · #212 sửa dụng cụ đo socket rồi mới đo · #211 presence dots + self-status picker + tương phản đo bằng code · #210 presence data layer + guest rule + hết spam status trong feed · #209 docs: mọi claim frontend hoặc bị xoá hoặc có chứng minh · #208 CI gate frontend thật (`oxlint --deny-warnings src` + `typecheck` + `build`, job mới `frontend-e2e` chạy Playwright với backend sống) · #207 clone mới reproduce được realtime (`.gitattributes`, `env.example.txt`, `make realtime`) · #206 chat delivery idempotent + spec browser đầu tiên pass thật · #205 **root cause của "realtime chết": server đặt tên subprotocol mà client không offer** · #203 kbar render loop · #201 WS transport fix · #200 status docs refresh · #199 presence docs + `test_docs_contract.py` gate · #198 worktree ignore + e2e evidence path · #197 API.md contract repairs · #196 presence socket refcount · #195 ruff debt 170→0 + CI `ruff` job · #189 presence service + WS (S5) · #188 Alembic single-head + `PresenceState` (S3/S4) · #185 restore baseline · #175 security regression pack (TA7-1) · #174 coverage floor + RBAC edge tests (TA6-3) · #164 load/perf baseline (TA6-2) · #163 ops maintenance (TA5-3) · #162 SQLite/PG dialect parity (TA5-2) · #161 WS auth + semantics (TA4-2) · #160 docs rewrite (TA3-3) · #159 pagination contract (TA3-1) · #149 observability + `/readyz` (TA6-1) · #148 N+1 + indexes (TA5-1) · #138 notification fan-out (TA4-1) · #134 LIKE escape + channel type enum (TA3-2) · #132 storage quota (TA2-3) · #130 authenticated `/uploads` read (TA2-2) · #128 upload ingress (TA2-1) · #126 jti request-scoped session (TA1-3) · #124 JWT secret governance (TA1-2) · #123 `/auth/refresh` (TA1-1) · #102 kanban guard · #101/#100/#99 rate-limit fallback + app README + demo-pack CI · #88 Postgres CI · #87 manage.py tests · #80 lifespan · #79 request log + healthz · #78 rate limiting · #28 UI redesign · Dependabot #81–#86.

> ⚠️ **Caveat khi verify bằng `git log`:** repo merge theo kiểu squash, nên **commit hash ≠ merge commit của PR**. Muốn biết PR nào đã landing, dùng `gh pr view <N> --json number,state,mergeCommit` — đừng kết luận từ `git log --oneline`. Chính hiểu nhầm này làm tài liệu cũ ghi sai trạng thái #123–#159 là "đang mở" cả tuần sau khi chúng đã merge.

**Test baseline hiện tại:** `cd backend && .venv/Scripts/python -m pytest -q` → **810 tests / 60 file** (SQLite), và `cd app && bunx playwright test --workers=1` → **37 tests / 10 spec file**. Hai con số này đổi theo từng PR — chạy lại lệnh trước khi quote, đừng tin dòng này.

---

## 4. Hiện trạng kỹ thuật

```
stw/                           ← monorepo (git, branch main — lấy sha bằng `git log -1 --format=%h`)
├── app/                       ← Next.js 16 frontend
│   ├── src/app/dashboard/     ← overview, kanban, chat, calendar, wiki, files, settings
│   ├── src/app/api/          ← BFF route handlers (proxy session cookie → backend)
│   ├── src/features/         ← chat (WS hook), calendar, projects, kanban…
│   ├── tests/                ← 10 Playwright spec + helpers, 37 test (CI `frontend-e2e`)
│   └── design-references/    ← usages.json: ledger adaptation theo Zero Native Design Rule
├── backend/                   ← FastAPI + Alembic + Docker Compose
│   ├── routers/              ← 15 domain routers (thêm presence), 51 HTTP paths + 2 WS routes
│   ├── alembic/versions/     ← head prs01_presence_state (1 head duy nhất)
│   └── test_*.py             ← 810 tests / 60 files, full suite xanh (SQLite + Postgres);
│                                test_ws_handshake_subprotocol.py chặn hồi quy RFC 6455 §4.1
├── docs/API.md               ← endpoint map + realtime + BFF map + changelog
├── docs/OPS.md               ← backup / retention / verification
├── docs/PERF-BASELINE.md     ← benchmark + load evidence
├── CONTRIBUTING.md           ← branch/PR flow, checks, conventions
├── README.md / RELEASE-CHECKLIST.md / PROJECT-STATUS.md (file này)
├── Makefile                  ← make dev / test / realtime / verify
├── scripts/demo-packs/       ← busy-workspace.json + load/make pack scripts
└── .github/workflows/ci.yml  ← CI 6 jobs: ruff, backend, backend-pg, frontend, frontend-e2e, demo-pack
```

- **Stack frontend:** Next.js 16.3.5 + React 19.2.4 + TS 5.7.2 strict + Tailwind v4 (CSS-first, không có `tailwind.config.*`) + shadcn/ui **trên Base UI (không phải Radix)** — dùng `render={<Button/>}` thay vì `asChild` — + dnd-kit + TanStack Query 5 + next-themes (dark default)
- **Stack backend:** FastAPI + SQLAlchemy 2.0 + Alembic + JWT (`jose`, access 1 tuần / refresh 7 ngày, httpOnly cookie) + bcrypt
- **DB:** SQLite local default (`sqlite:///./stw.db`); PostgreSQL 16 qua Docker Compose (`postgres` + `backend` services, bắt buộc `backend/.env`)
- **Auth:** register / login / me / logout / logout-all / **refresh** qua cookie + session revocation theo `jti`. `/auth/refresh` đã merge (#123, commit `6031e41`): refresh token single-use, mỗi lần rotate mint row kế tiếp trong cùng `family_id`; replay token đã rotate = thu hồi **cả family** + `401`. Startup từ chối default secret ngoài dev/test (#124).
- **Realtime:** 2 socket — `/ws/channels/{id}` (rooms `chan:` + `user:`) và `/ws/workspaces/{id}/presence` (rooms `workspace:` + `user:`), chung một handshake resolver và bảng close code 4401/4403/4404. `chan:` và `workspace:` rời nhau (`presence_update` không sang chat socket), nhưng `user:` thì *cố ý* nằm ở cả hai: dashboard tab chỉ giữ presence socket vẫn phải nhận `notification_created`, nên trang chat nhận frame đó hai lần — coi nó là "có gì mới, refetch", không phải delta để merge. **Rooms + presence refcount đều là in-memory → chỉ đúng với 1 uvicorn worker**; scale ngang cần shared store. Mỗi lần gửi cho 1 peer bị bound bởi `ws.WS_SEND_TIMEOUT_SECONDS` (2s): peer treo hoặc chết thì bị log + prune ngay trong broadcast, nên 1 socket half-open không còn quyết định thời gian chờ của cả room nữa (đo trước: 1 peer stall 5s → broadcast 5.00s và 3 tin sau 15.03s; đo sau: 2.00s rồi 0.00s). Gửi vẫn tuần tự và vẫn nằm trên request path của POST — `asyncio.gather` bị loại vì TestClient mỗi socket một event loop riêng. Blocking work đã rời khỏi loop (S6-RT5): một lần bcrypt 264–352ms ở `POST /auth/register`, `POST /auth/login`, `DELETE /users/me` nay chạy trên worker thread qua `run_in_threadpool` (`dependencies.verify_password_async` / `get_password_hash_async`); `bench/loop_blocking_probe.py` đo 12 register đồng thời thì khoảng trống dài nhất mà loop bị bỏ rơi giảm **4904ms → 110–211ms** (một ticker 10ms không tick nổi trong suốt khoảng đó). Hai write của presence socket (`_set_and_publish`, `_touch`) **đã thử offload và revert**: p50 8–11ms/20s mỗi tab, và thread hop làm fan-out của nó thành resumed step → send sang socket của portal khác bị park, `test_ws_connect_broadcasts_online` treo thay vì fail (ghi trong docstring của chính hàm). Phần blocking còn lại là ~11ms SQLAlchemy *trên mỗi request* — chưa đi, xem §6. Presence: `online` ghi ở socket *đầu tiên*, `offline` chỉ ở socket *cuối cùng*; read-time decay `online`→`away` (300s) và →`offline` (1800s), không có scheduler hay TTL column. Frame inbound: chỉ `{"type":"presence","status":…}` mới đổi status — mọi frame khác là heartbeat, nó chỉ reset `last_seen` (giữ nguyên status + message, không broadcast) và trả `pong`; status sai/thiếu trả `presence_error` chứ không `pong` dối; `{"type":"bye"}` thì server chủ động close. Client gửi heartbeat mỗi 20s (`use-presence.tsx`), nếu không thì tab idle tự xám đi sau 5 phút.
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
- [ ] **S6 còn nợ (UI)**, branch tiếp theo `feat/rt-presence-ui-2`: ba bề mặt chưa nối presence — (1) roster sắp xếp theo presence, (2) dot trong dialog New DM, (3) chữ "N online" ở overview. Chỉ (1) đã có reference trong ledger (`chat-collab__zulip`, `status: "sourced"` — rule: đang hoạt động trước, rồi idle, offline gom xuống cuối); (2) và (3) **chưa có record nào**, nên theo quy trình §Design-Reference của `AGENTS.md` là tìm nguồn + chép vào catalog *trước khi* thi công, không tự chế visual. Riêng (3) còn một nợ kỹ thuật nhỏ: `onlineCount` đã bị bỏ khỏi presence context trong #219 vì không consumer nào đọc nó; làm mục này thì tính trực tiếp từ `byUser` trong component, hoặc đưa lại field kèm test chứng minh có người dùng.
- [x] **S6 presence UI (frontend)** — đã merge (#210 data layer + guest rule, #211 dots + self-status picker). 4 token trạng thái + `PresenceDot` (dùng lại `AvatarBadge` của shadcn/ui, không tự chế geometry), dot trên DM list và member table, picker trong user menu, 7 key tiếng Việt đầu tiên gọi `t()` ngoài sidebar. Tương phản **đo bằng code**: `app/tests/presence-dot.spec.ts` chạy 4 trạng thái × 11 theme × 2 mode với sàn WCAG 1.4.11 = 3:1, không phải nhìn screenshot.
- [x] Quyết định: `POST /presence/me` **ngừng** ghi `Activity` row (`verb=set_presence`). Lý do: path socket (`presence.py:_set_and_publish`) vốn không ghi dòng nào → feed là coin flip theo transport mà client chọn; `services.log_activity` không dedup/cooldown; overview feed chỉ giữ 8 item và render raw verb. `PresenceState` mới là bảng của lịch sử status. Thi công ở PR presence-data-layer kèm test "POST presence không tạo Activity row".

**Kỹ thuật còn nợ**
- [x] 🔴 → ✅ **Mọi WebSocket của browser đều chết ở bắt tay** (#205 + #206) — đây là root cause thật của mục "chat realtime không delivers" mà doc này từng mô tả sai hai lần. Chuỗi lỗi, mỗi mắt xích đọc trực tiếp trong code:
  1. `app/src/lib/realtime/use-websocket.ts:95` → `new WebSocket(url)` **không truyền `protocols`**, nên client không offer subprotocol nào.
  2. `backend/dependencies.py` path cookie trả `accepted_subprotocol = None`.
  3. `channels.py` / `presence.py` gọi `accept(subprotocol=subproto or WS_SUBPROTOCOL)` → 101 nêu `stw-ws`.
  4. Starlette 1.6 `accept()` nhét thẳng giá trị vào ASGI message, **không đối chiếu offer**.
  5. uvicorn 0.52 `websockets_impl.process_subprotocol` được override để "return whatever subprotocol is sent in the accept message"; bản sansio append header `Sec-WebSocket-Protocol`.
  6. RFC 6455 §4.1 step 6: client **MUST fail** khi server nêu protocol mình không offer → Chrome abort sau 101, hook reconnect (backoff 1→5s) nên một page mở 4 socket.
  - Vì sao 770 test xanh: `starlette/testclient.py:124` chỉ *ghi* `accepted_subprotocol` chứ không validate, và không call site `websocket_connect(` nào truyền `subprotocols=`. Vì sao người (kể cả agent) kết luận sai: dòng `[accepted]` trong log uvicorn chỉ chứng minh **application** accept, không chứng minh browser hoàn tất handshake.
  - Defect thứ hai cùng dòng: path ticket trả bare `stw-ws` trong khi client offer `stw-ws.<ticket>` (`ws.py:_ws_ticket_subprotocol`) → cũng là giá trị không được offer.
  - Bằng chứng ngược có sẵn trong repo trước khi sửa: `app/qa-evidence/ws-transport-realtime-report.json` ghi `message-reaches-peer-context: FAIL, rendered=false inDom=false sameSocketUrl=true` — 1 socket/page, cùng URL, 0 frame.
  - Regression guard: `backend/test_ws_handshake_subprotocol.py` assert ở tầng ASGI (`picked is None or picked in offered`) — chạy trong cả 2 backend job, không cần port hay browser. RED trước khi sửa: 3 fail + 1 ImportError.
  - Hệ quả lộ ra sau khi handshake sống: author nhận **2 bản** message (broadcast không `exclude` + refetch lúc settle) → sửa bằng dedupe theo `id` phía client (#206). Server-side `exclude` không biểu đạt được: HTTP handler không giữ object WebSocket nào, còn exclude theo user sẽ giết luôn tab khác của chính người gửi.
  - Đo sau fix: `app/tests/realtime-delivery.spec.ts` pass; mutation check (đặt lại bug) làm spec fail; probe tạm ở `messages.py` ghi `delivered=2` cho cả 7 broadcast.
- [x] 🔶 → ✅ **`src/components/kbar/use-search-actions.ts:40` lặp vô hạn** — đã sửa (#203). Root cause: effect dep `[searchQuery, routerPush]` trong khi caller truyền inline arrow (`kbar/index.tsx:66`), cộng với `setResults({…})` luôn cấp object mới → chu trình render. Hệ quả phụ: debounce 250ms bị reset mỗi render nên kbar data search gần như không bao giờ chạy. Đo bằng chứng thật: **6007 → 0** cảnh báo `Maximum update depth` trên cùng một kịch bản load trang.
- [ ] `manage.py create-user` **chạy được trên DB trống**: hiện query `users` ở `backend/manage.py:227` nhưng chỉ gọi `create_all` ở `:231`, nên lần chạy đầu tiên trên DB mới toang với `no such table: users`. Cần quyết định lệnh nào sở hữu schema creation.
- [ ] `POST /api/notifications` action `mark-all-read` đang proxy tới `POST /notifications/mark-all-read` — **route backend không tồn tại**, handler hiện trả 405. Hoặc thêm route, hoặc bỏ handler.
- [ ] `app/src/features/workspace/components/workspace-settings-page.tsx:31` liệt kê roles `owner|admin|member|**viewer**` trong khi backend chỉ có `owner|admin|member|**guest**` (`authorization.py:17`). Dropdown cho phép chọn "viewer" — role không tồn tại ở server.
- [ ] Chuông notification (`app/src/features/notifications/utils/store.ts:105`) vẫn đọc `mockNotifications` tại `:23`, chưa nối `GET /api/notifications` thật.
- [x] CI gate `ruff check` (#195): 170 lỗi về 0. `ruff format` vẫn **không** gate.
- [x] `app/.env.local` từng để `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` trong khi CONTRIBUTING bắt dùng `localhost`: `session_token` là `SameSite=Lax` nên khác hostname = cookie không gửi lên WS upgrade → **mọi handshake chat + presence bị từ chối trước `accept()`** (app gửi 4401, browser chỉ nhận HTTP 403), và console thì im lặng. Nay `env.example.txt` đã chứa biến này (#207) nên không còn bước "thêm tay", và `lib/realtime/use-websocket.ts` log rõ tên lỗi + hostname rồi **không** retry (#201).
- [x] Frontend CI (#208): job `frontend` chạy `oxlint --deny-warnings src` + `typecheck` + `build`; job `frontend-e2e` chạy 37 Playwright test với backend sống (tự khởi động qua `playwright.config.ts`, `workers=1`). Lần chạy đầu của job này đỏ vì config tìm `backend/.venv` mà CI không tạo → đã sửa trong cùng PR; hiện 6/6 job xanh.
- [ ] **`app/src/app/api/workspace/members/route.ts:49-57` trả `seededMembers` (dữ liệu bịa)** khi thiếu cookie hoặc backend không reachable, và PATCH thì mutate thẳng fixture trong bộ nhớ. `workspace-settings-invite.spec.ts` từng assert đúng dữ liệu bịa đó (`Demo Admin`, `Jane Member`) — đã viết lại trong #208. Presence dot chỉ render khi `user_id` có trong payload nên row bịa không dot, nhưng bản thân cơ chế fallback vẫn là defect chưa ai xử lý.
- [x] 🔶 → ✅ **Quan sát "socket đóng dưới tải" là lỗi của dụng cụ đo, không phải của sản phẩm.** Trước lần đo này, `watchSockets` gắn listener *sau* khi `openPage` đã điều hướng (Playwright chỉ báo socket mở **sau khi** listener được gắn) và bộ lọc `:8000` gộp chung hai namespace — mà từ #211 một trang chat giữ **hai** socket backend (channel + presence). Con số "2→3 socket" vì thế không đo cái nó tưởng là đo. Đo lại với dụng cụ đã sửa (tách theo đường dẫn URL, gắn trước điều hướng):
  - toàn bộ suite song song, 32/32 pass, mỗi page **chính xác 1 channel socket**;
  - không có close nào mang mã keepalive: 4 channel + 25 presence đều là `1001` (client chủ động đóng). Chỉ **1** lần `1005` trong 30 handshake, và nó không tái hiện ở lần chạy sau đó;
  - watchdog trôi event-loop: **0 lần** vượt ngưỡng 2s — và bản thân watchdog có positive control (`test_app_loop_watchdog.py`: bắt được `time.sleep(3.5)`, không báo oan khi loop khỏe);
  - giả thuyết keepalive bị **bác** bằng phản chứng: chạy với `--ws-ping-interval 5 --ws-ping-timeout 2` vẫn chỉ ra `1001`, không có `1005`.
  Hệ quả: PR "offload blocking calls" không còn là bản vá cho socket chết. Nó vẫn đáng làm, và **đã làm ở S6-RT5** — vì lý do khác và có số. Một lần bcrypt 12-round đo **264–352ms** (số tuyệt đối trôi theo xung CPU, hãy đọc tỉ lệ), và nó chạy trên đúng event loop đang giữ mọi socket. Sau khi offload bcrypt (`dependencies.verify_password_async` / `get_password_hash_async`), `bench/loop_blocking_probe.py` đo 12 lần register đồng thời:

  | | 12 request đồng thời | khoảng trống loop dài nhất |
  |---|---|---|
  | trước | 4945 ms (= 14.7 lần hash) | **4904 ms** |
  | sau | 1106–1288 ms (= 4.1–4.7 lần hash) | **110–211 ms** |

  Cột thứ hai mới là con số realtime: đó là khoảng thời gian mọi socket trong process không được phục vụ (ticker 10 ms trên cùng loop không tick nổi). Phần còn lại tỉ lệ với *số request* (4 → 54ms, 8 → 92ms, 12 → ~130ms) chứ không tỉ lệ với số lần hash — tức nó là ~11 ms SQLAlchemy sync trên mỗi request path vẫn nằm lại trên loop, không phải bcrypt.
- [ ] **Trần connection pool: 15 request đồng thời.** `QueuePool(size 5 + overflow 10)` — chạy `python bench/loop_blocking_probe.py 20` thì đúng 5 request trả 500, mỗi cái sau **151.5 giây** (xa hơn nhiều `pool_timeout` 30s của chính pool; vì sao xa đến thế vẫn là một phần của defect), và teardown khi rollback ném `sqlite3.ProgrammingError: Cannot operate on a closed database` — nghĩa là hết pool không chỉ trả 500 muộn mà còn trả một connection đã hỏng về lại pool. Defect có sẵn từ trước, S6-RT5 không làm nặng hơn (request ngắn hơn thì giữ connection ít thời gian hơn). Hướng xử lý cần quyết định: nâng `pool_size`/`max_overflow`, hay đừng giữ connection suốt request (`get_db`), hay `pool_timeout`, và Postgres trong `docker-compose.yml` thực tế cho phép bao nhiêu.
- [ ] `bun run format:check` chưa phải gate. Con số "329/330 file chưa format" từng ghi trong doc là **artifact CRLF** (`core.autocrlf=true`, không có `.gitattributes`, blob trong commit là LF sạch); `.gitattributes` (#207) sửa gốc. Working tree cũ vẫn CRLF tới khi checkout lại, nên cần một PR format riêng sau khi wave này xong.

**Release**
- [ ] Giải nốt #85 sau khi có smoke test; triage #193/#194 (major) riêng.
- [ ] Release local-first theo `RELEASE-CHECKLIST.md` §5
- [ ] Cloud deploy (Vercel + Neon/Supabase + Render/Fly) — để sau; lưu ý realtime là in-memory nên **1 worker duy nhất** cho tới khi có shared room store.

---

*Soạn bởi Vex — số liệu verify trực tiếp trên repo ngày 19/09/2026: `pytest -q` / `--collect-only`, `alembic heads`, `coverage report`, `gh pr list --state open`, route walk từ `app.routes`, và `git log`/`gh pr view` cho trạng thái merge.*
