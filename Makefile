# Student Team Workspace — one-command dev shortcuts (pure make, no extra deps).
#
#   make dev       — Postgres (Docker) + backend (uvicorn :8000) + frontend (Next.js :3000, webpack)
#   make test      — backend pytest + frontend typecheck
#   make realtime  — start both servers and prove a message crosses to a second browser
#   make verify    — test + realtime
#   make seed      — placeholder until T045 manage.py lands
#
# Requires: Docker (for Postgres), backend/.venv, and `bun install` in app/.

ifeq ($(wildcard backend/.venv/Scripts/python.exe),)
BACKEND_PY := .venv/bin/python
else
BACKEND_PY := .venv/Scripts/python.exe
endif

.PHONY: dev test seed bench realtime verify

dev:
	docker compose -f backend/docker-compose.yml up -d postgres
	cd backend && ENVIRONMENT=dev $(BACKEND_PY) -m uvicorn app:app --reload --port 8000 & \
	cd app && bun run dev:webpack

test:
	cd backend && $(BACKEND_PY) -m pytest -q
	cd app && bun run typecheck

# The point of this target is that "realtime works" is never an inference from
# an access-log line again: uvicorn logged `[accepted]` for every socket while
# the browser refused each upgrade, so the proof has to be a frame arriving in a
# second browser context. playwright.config.ts starts and stops both servers.
realtime:
	cd app && bunx playwright test tests/realtime-delivery.spec.ts

verify: test realtime

seed:
	@echo "TODO wired to T045 manage.py"

bench:
	cd backend && $(BACKEND_PY) bench/run_bench.py
