# Student Team Workspace — Project Status

> **Ngày cập nhật:** 19/09/2026 (GMT+7)
> **Trạng thái:** 🟢 W0–W10 + UI redesign + toàn bộ T-wave/TA-wave (hardening) đã merge trên `main`; đang chạy S-wave (realtime presence)
> **Repo:** `skappafrost/student-team-workspace`, public, GitHub Flow (`feat/*` + `harden/*` branches → draft PR → Skappa squash-merge)
> **Verified on:** `pytest -q` **770 tests collected / 769 passed** (SQLite, `backend/.venv`; the one local failure is the known Windows tmp-file-lock flake — passes in isolation, green on Linux CI) · `alembic heads` = 1 (`prs01_presence_state`) · coverage **91.48%** với floor `fail_under = 90` (`backend/pyproject.toml:50`) · CI **5 jobs** (`ruff`, `backend`, `backend-pg`, `frontend`, `demo-pack`) — đo trực tiếp trên `main` @ `21bc04c` ngày 19/09; chạy lại lệnh trước khi quote.

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
| S-wave | Realtime presence: S3 single-head, S4 `PresenceState` model, S5 service + HTTP set/list + WS fan-out, **S6 presence UI (frontend)** | 🔄 S3–S5 đã merge (#188, #189); **S6 chưa làm** |

**Merged trên `main` (mới nhất trước):** #208 CI gate frontend thật (`oxlint --deny-warnings src` + `typecheck` + `build`, job mới `frontend-e2e` chạy Playwright với backend sống) · #207 clone mới reproduce được realtime (`.gitattributes`, `env.example.txt`, `make realtime`) · #206 chat delivery idempotent + spec browser đầu tiên pass thật · #205 **root cause của "realtime chết": server đặt tên subprotocol mà client không offer** · #203 kbar render loop · #201 WS transport fix · #200 status docs refresh · #199 presence docs + `test_docs_contract.py` gate · #198 worktree ignore + e2e evidence path · #197 API.md contract repairs · #196 presence socket refcount · #195 ruff debt 170→0 + CI `ruff` job · #189 presence service + WS (S5) · #188 Alembic single-head + `PresenceState` (S3/S4) · #185 restore baseline · #175 security regression pack (TA7-1) · #174 coverage floor + RBAC edge tests (TA6-3) · #164 load/perf baseline (TA6-2) · #163 ops maintenance (TA5-3) · #162 SQLite/PG dialect parity (TA5-2) · #161 WS auth + semantics (TA4-2) · #160 docs rewrite (TA3-3) · #159 pagination contract (TA3-1) · #149 observability + `/readyz` (TA6-1) · #148 N+1 + indexes (TA5-1) · #138 notification fan-out (TA4-1) · #134 LIKE escape + channel type enum (TA3-2) · #132 storage quota (TA2-3) · #130 authenticated `/uploads` read (TA2-2) · #128 upload ingress (TA2-1) · #126 jti request-scoped session (TA1-3) · #124 JWT secret governance (TA1-2) · #123 `/auth/refresh` (TA1-1) · #102 kanban guard · #101/#100/#99 rate-limit fallback + app README + demo-pack CI · #88 Postgres CI · #87 manage.py tests · #80 lifespan · #79 request log + healthz · #78 rate limiting · #28 UI redesign · Dependabot #81–#86.

> ⚠️ **Caveat khi verify bằng `git log`:** repo merge theo kiểu squash, nên **commit hash ≠ merge commit của PR**. Muốn biết PR nào đã landing, dùng `gh pr view <N> --json number,state,mergeCommit` — đừng kết luận từ `git log --oneline`. Chính hiểu nhầm này làm tài liệu cũ ghi sai trạng thái #123–#159 là "đang mở" cả tuần sau khi chúng đã merge.

**Test baseline hiện tại:** `cd backend && .venv/Scripts/python -m pytest -q` → **775 tests / 57 file** (SQLite), và `cd app && bunx playwright test` → **7 specs / 4 files**. Hai con số này đổi theo từng PR — chạy lại lệnh trước khi quote, đừng tin dòng này.

---

## 4. Hiện trạng kỹ thuật

```
stw/                           ← monorepo (git, branch main — lấy sha bằng `git log -1 --format=%h`)
├── app/                       ← Next.js 16 frontend
│   ├── src/app/dashboard/     ← overview, kanban, chat, calendar, wiki, files, settings
│   ├── src/app/api/          ← BFF route handlers (proxy session cookie → backend)
│   ├── src/features/         ← chat (WS hook), calendar, projects, kanban…
│   ├── tests/                ← 4 Playwright spec + helpers (CI `frontend-e2e`)
│   └── design-references/    ← usages.json: ledger adaptation theo Zero Native Design Rule
├── backend/                   ← FastAPI + Alembic + Docker Compose
│   ├── routers/              ← 15 domain routers (thêm presence), 51 HTTP paths + 2 WS routes
│   ├── alembic/versions/     ← head prs01_presence_state (1 head duy nhất)
│   └── test_*.py             ← 775 tests / 57 files, full suite xanh (SQLite + Postgres);
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
- [ ] **S6 — presence UI (frontend)**, branch `feat/rt-presence-ui`: consume `GET /workspaces/{id}/presence` + `/ws/workspaces/{id}/presence`, dot trên DM list / member table / user menu. **Đã thi công:** 4 token trạng thái + `PresenceDot` (dùng lại `AvatarBadge` của shadcn/ui, không tự chế geometry), dot trên DM list và member table, picker trong user menu, 7 key tiếng Việt đầu tiên gọi `t()` ngoài sidebar. Tương phản **đo bằng code**: `app/tests/presence-dot.spec.ts` chạy 4 trạng thái × 11 theme × 2 mode với sàn WCAG 1.4.11 = 3:1, không phải nhìn screenshot. **Chưa làm:** sắp xếp roster theo presence (record zulip vẫn `sourced`) và dot trong dialog New DM. Vẫn theo Zero Native Design Rule: `element-web` là AGPL nên chỉ lấy spec, không copy code.
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
- [x] `app/.env.local` từng để `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` trong khi CONTRIBUTING bắt dùng `localhost`: `session_token` là `SameSite=Lax` nên khác hostname = cookie không gửi lên WS upgrade → **mọi handshake chat + presence 4401 trước `accept()`**, và console thì im lặng. Nay `env.example.txt` đã chứa biến này (#207) nên không còn bước "thêm tay", và `lib/realtime/use-websocket.ts` log rõ tên lỗi + hostname rồi **không** retry (#201).
- [x] Frontend CI (#208): job `frontend` chạy `oxlint --deny-warnings src` + `typecheck` + `build`; job `frontend-e2e` chạy 7 Playwright test với backend sống (tự khởi động qua `playwright.config.ts`). Lần chạy đầu của job này đỏ vì config tìm `backend/.venv` mà CI không tạo → đã sửa trong cùng PR; hiện 6/6 job xanh.
- [ ] **`app/src/app/api/workspace/members/route.ts:49-57` trả `seededMembers` (dữ liệu bịa)** khi thiếu cookie hoặc backend không reachable, và PATCH thì mutate thẳng fixture trong bộ nhớ. `workspace-settings-invite.spec.ts` từng assert đúng dữ liệu bịa đó (`Demo Admin`, `Jane Member`) — đã viết lại trong #208. Presence dot chỉ render khi `user_id` có trong payload nên row bịa không dot, nhưng bản thân cơ chế fallback vẫn là defect chưa ai xử lý.
- [x] 🔶 → ✅ **Quan sát "socket đóng dưới tải" là lỗi của dụng cụ đo, không phải của sản phẩm.** Trước lần đo này, `watchSockets` gắn listener *sau* khi `openPage` đã điều hướng (Playwright chỉ báo socket mở **sau khi** listener được gắn) và bộ lọc `:8000` gộp chung hai namespace — mà từ #211 một trang chat giữ **hai** socket backend (channel + presence). Con số "2→3 socket" vì thế không đo cái nó tưởng là đo. Đo lại với dụng cụ đã sửa (tách theo đường dẫn URL, gắn trước điều hướng):
  - toàn bộ suite song song, 32/32 pass, mỗi page **chính xác 1 channel socket**;
  - không có close nào mang mã keepalive: 4 channel + 25 presence đều là `1001` (client chủ động đóng). Chỉ **1** lần `1005` trong 30 handshake, và nó không tái hiện ở lần chạy sau đó;
  - watchdog trôi event-loop: **0 lần** vượt ngưỡng 2s — và bản thân watchdog có positive control (`test_app_loop_watchdog.py`: bắt được `time.sleep(3.5)`, không báo oan khi loop khỏe);
  - giả thuyết keepalive bị **bác** bằng phản chứng: chạy với `--ws-ping-interval 5 --ws-ping-timeout 2` vẫn chỉ ra `1001`, không có `1005`.
  Hệ quả: PR "offload blocking calls" không còn là bản vá cho socket chết. Nó vẫn đáng làm, nhưng vì lý do khác và có số: `POST /auth/register` hết **295–405ms** wall, toàn bộ nằm trên event loop trong `async def` (`dependencies.py:251` ← `routers/auth.py:69`), tức mỗi lần đăng nhập làm mọi socket đang chạy chờ ~300ms. Phải có ~60 lần đăng nhập nối tiếp mới chạm ngưỡng 20s của keepalive — đó là lý do không socket nào chết.
- [ ] `bun run format:check` chưa phải gate. Con số "329/330 file chưa format" từng ghi trong doc là **artifact CRLF** (`core.autocrlf=true`, không có `.gitattributes`, blob trong commit là LF sạch); `.gitattributes` (#207) sửa gốc. Working tree cũ vẫn CRLF tới khi checkout lại, nên cần một PR format riêng sau khi wave này xong.

**Release**
- [ ] Giải nốt #85 sau khi có smoke test; triage #193/#194 (major) riêng.
- [ ] Release local-first theo `RELEASE-CHECKLIST.md` §5
- [ ] Cloud deploy (Vercel + Neon/Supabase + Render/Fly) — để sau; lưu ý realtime là in-memory nên **1 worker duy nhất** cho tới khi có shared room store.

---

*Soạn bởi Vex — số liệu verify trực tiếp trên repo ngày 19/09/2026: `pytest -q` / `--collect-only`, `alembic heads`, `coverage report`, `gh pr list --state open`, route walk từ `app.routes`, và `git log`/`gh pr view` cho trạng thái merge.*
