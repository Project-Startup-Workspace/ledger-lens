# Developer entry points. Run `make help` for the list.
SHELL := /bin/bash
UV ?= uv
AGENTS := agents
WEB := web

.PHONY: help setup check lint typecheck test test-integration emulators api a2a web up demo-data train eval clean

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

EMULATOR_ENV := FIRESTORE_EMULATOR_HOST=localhost:8681 STORAGE_EMULATOR_HOST=http://localhost:4443 GOOGLE_CLOUD_PROJECT=ledger-lens-test

emulators: ## Start the Firestore and Cloud Storage emulators in Docker
	docker run -d --rm --name ll-firestore -p 8681:8681 gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators gcloud emulators firestore start --host-port=0.0.0.0:8681
	docker run -d --rm --name ll-storage -p 4443:4443 fsouza/fake-gcs-server -scheme http -port 4443 -public-host localhost:4443

test-integration: ## Run the cloud adapter tests against the emulators (make emulators first)
	cd $(AGENTS) && $(EMULATOR_ENV) $(UV) run pytest -m integration

api: ## Run the API on :8080 (offline models unless .env says otherwise)
	cd $(AGENTS) && $(UV) run uvicorn ledger_lens.api.app:app --reload --port 8080

a2a: ## Run the AuditPulse A2A service on :8081
	cd $(AGENTS) && $(UV) run uvicorn ledger_lens.a2a_server:app --port 8081

web: ## Run the officer web app on :3000 (expects `make api`)
	cd $(WEB) && npm run dev

up: ## Run web, API and A2A in containers (docker compose)
	docker compose up --build

demo-data: ## Regenerate the synthetic demo notebooks, statements and fixtures
	cd $(AGENTS) && $(UV) run python scripts/generate_demo_data.py

train: ## Retrain the illustrative risk model on synthetic applicants
	cd $(AGENTS) && $(UV) run python -m ledger_lens.risk.training

eval: ## Score read accuracy per script and the risk model's fairness (eval/results)
	cd $(AGENTS) && $(UV) run python -m ledger_lens.evaluation

clean: ## Remove caches and local runtime data
	rm -rf $(AGENTS)/.pytest_cache $(AGENTS)/.mypy_cache $(AGENTS)/.ruff_cache .data
