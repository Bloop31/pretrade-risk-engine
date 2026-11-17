UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install run test lint typecheck fmt check up down loadtest

help: ## Show available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies from the lockfile
	$(UV) sync --locked

run: ## Run the API locally with auto-reload (needs a Redis on REDIS_URL)
	$(UV) run uvicorn risk_service.main:create_app --factory --reload --host $(HOST) --port $(PORT)

test: ## Run the test suite with coverage
	$(UV) run pytest --cov --cov-report=term-missing

lint: ## Lint and check formatting
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## mypy --strict on src/
	$(UV) run mypy

fmt: ## Auto-fix lint issues and format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

check: lint typecheck test ## Everything CI runs

up: ## Start api + redis with docker compose
	docker compose up --build -d

down: ## Stop docker compose services
	docker compose down

loadtest: ## Fire load at a running service (see scripts/loadtest.py --help)
	$(UV) run python scripts/loadtest.py
