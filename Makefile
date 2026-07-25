.PHONY: help install test test-e2e lint typecheck client-test build-client package

help: ## Show available development commands
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and browser-development dependencies
	python -m pip install -e ".[dev]"
	cd src/leika/client && npm ci

test: ## Run Python unit tests
	pytest --ignore=tests/e2e

test-e2e: ## Run Playwright browser tests
	pytest tests/e2e -n auto

lint: ## Check Python formatting and lint rules
	ruff check src tests examples scripts
	ruff format --check src tests examples scripts

typecheck: ## Type-check the Python package and examples
	pyright src examples

client-test: ## Type-check, lint, and unit-test the browser client
	cd src/leika/client && npm run typecheck && npm run lint && npm test

build-client: ## Build the single-file browser client
	cd src/leika/client && npm ci && npm run build

package: ## Build distributions and enforce the wheel-size ceiling
	python -m build
	python scripts/check_wheel.py dist/*.whl
