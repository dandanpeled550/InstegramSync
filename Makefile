# Insta Saver — developer entry points. Every target is safe on a tree where an area does not exist yet.
# Tools: uv (Python), supabase CLI, deno (edge functions), npm (frontend). Nothing is installed by this file.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

HAS_BACKEND  := $(wildcard backend/pyproject.toml)
HAS_FRONTEND := $(wildcard frontend/package.json)
HAS_FUNCTIONS := $(wildcard supabase/functions)

.PHONY: help dev test test-db lint fmt process process-prod replay eval

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

dev: ## Start local Supabase (Docker must be running)
	supabase start

test: ## Unit tests (excludes tests/db, which needs a running database: see test-db)
ifneq ($(HAS_BACKEND),)
	cd backend && uv run pytest --ignore=tests/db ../tests
else
	@echo "test: no backend/ yet, skipping"
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm test --if-present
endif

test-db: ## DB tests against a local Supabase (run `make dev` first)
ifneq ($(HAS_BACKEND),)
	cd backend && uv run pytest ../tests/db
else
	@echo "test-db: no backend/ yet, skipping"
endif

lint: ## Lint and format-check everything that exists
ifneq ($(HAS_BACKEND),)
	cd backend && uv run ruff check . && uv run ruff format --check .
else
	@echo "lint: no backend/ yet, skipping python"
endif
ifneq ($(HAS_FUNCTIONS),)
	deno lint supabase/functions && deno fmt --check supabase/functions
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm run lint --if-present
endif

fmt: ## Auto-format
ifneq ($(HAS_BACKEND),)
	cd backend && uv run ruff check --fix . && uv run ruff format .
endif
ifneq ($(HAS_FUNCTIONS),)
	deno fmt supabase/functions
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && npm run fmt --if-present
endif
	@echo "fmt: done"

process: ## Run the worker once against the local stack (APP_ENV=local)
ifneq ($(wildcard backend/app/process.py),)
	cd backend && APP_ENV=local uv run python -m app.process
else
	@echo "process: backend/app/process.py not implemented yet"
endif

# The production worker only runs from a clean checkout of `main` that sits exactly on a release tag.
process-prod: ## Run the worker against PRODUCTION (main, clean, tagged only)
	@branch="$$(git rev-parse --abbrev-ref HEAD)"; \
	if [ "$$branch" != "main" ]; then echo "process-prod: refusing, on '$$branch' (need main)"; exit 1; fi; \
	if [ -n "$$(git status --porcelain)" ]; then echo "process-prod: refusing, working tree not clean"; exit 1; fi; \
	if ! git describe --exact-match --tags --match 'v[0-9]*' HEAD >/dev/null 2>&1; then \
	  echo "process-prod: refusing, HEAD is not on a release tag (vX.Y.Z)"; exit 1; fi; \
	echo "process-prod: checks passed ($$(git describe --exact-match --tags HEAD))"; \
	echo "process-prod: worker not implemented yet"

replay: ## Replay fixtures into the receiver (stub until M1)
	@echo "replay: not implemented yet (test-engineer: scripts/replay*)"

eval: ## Run the AI eval harness (stub until the harness exists)
	@echo "eval: not implemented yet (ai-engineer: evals/)"
