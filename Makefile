# Student Team Workspace — one-command dev shortcuts (pure make, no extra deps).
#
#   make dev   — Postgres (Docker) + backend (uvicorn :8000) + frontend (Next.js :3000, webpack)
#   make test  — backend pytest + frontend typecheck
#   make seed  — placeholder until T045 manage.py lands
#
# Requires: Docker (for Postgres), backend/.venv, and `bun install` in app/.

ifeq ($(wildcard backend/.venv/Scripts/python.exe),)
BACKEND_PY := .venv/bin/python
else
BACKEND_PY := .venv/Scripts/python.exe
endif

.PHONY: dev test seed

dev:
	docker compose -f backend/docker-compose.yml up -d postgres
	cd backend && $(BACKEND_PY) -m uvicorn app:app --reload --port 8000 & \
	cd app && bun run dev:webpack

test:
	cd backend && $(BACKEND_PY) -m pytest -q
	cd app && bun run typecheck

seed:
	@echo "TODO wired to T045 manage.py"
