# Developer entry points. Run `make help` for the list.
SHELL := /bin/bash
UV ?= uv
AGENTS := agents
WEB := web

.PHONY: help setup check lint typecheck test run-api run-web run demo-data eval clean

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

clean: ## Remove caches and local runtime data
	rm -rf $(AGENTS)/.pytest_cache $(AGENTS)/.mypy_cache $(AGENTS)/.ruff_cache .data
