# Developer entry points. Run `make help` for the list.
SHELL := /bin/bash
UV ?= uv
AGENTS := agents
WEB := web

.PHONY: help setup check lint typecheck test api a2a web demo-data train clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install Python and web dependencies and git hooks
	cd $(AGENTS) && $(UV) sync --all-extras
	@if [ -f $(WEB)/package.json ]; then cd $(WEB) && npm ci; fi
	$(UV) run --project $(AGENTS) pre-commit install

check: lint typecheck test ## Run every check that CI runs

lint: ## Lint and format-check Python and web code
	cd $(AGENTS) && $(UV) run ruff check . && $(UV) run ruff format --check .
	@if [ -f $(WEB)/package.json ]; then cd $(WEB) && npm run lint && npm run format:check; fi

typecheck: ## Type-check Python and web code
	cd $(AGENTS) && $(UV) run mypy
	@if [ -f $(WEB)/package.json ]; then cd $(WEB) && npm run typecheck; fi

test: ## Run the Python test suite
	cd $(AGENTS) && $(UV) run pytest

api: ## Run the API on :8080 (offline models unless .env says otherwise)
	cd $(AGENTS) && $(UV) run uvicorn ledger_lens.api.app:app --reload --port 8080

a2a: ## Run the AuditPulse A2A service on :8081
	cd $(AGENTS) && $(UV) run uvicorn ledger_lens.a2a_server:app --port 8081

demo-data: ## Regenerate the synthetic demo notebooks, statements and fixtures
	cd $(AGENTS) && $(UV) run python scripts/generate_demo_data.py

train: ## Retrain the illustrative risk model on synthetic applicants
	cd $(AGENTS) && $(UV) run python -m ledger_lens.risk.training

clean: ## Remove caches and local runtime data
	rm -rf $(AGENTS)/.pytest_cache $(AGENTS)/.mypy_cache $(AGENTS)/.ruff_cache .data
