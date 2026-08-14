.PHONY: help install install-docs test test-e2e lint typecheck client-test build-client docs gallery docs-serve package
UV_DEV = uv run --locked --extra dev
UV_DOCS = uv run --locked --extra docs


help: ## Show available development commands
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and browser-development dependencies
	uv sync --locked --extra dev
	$(UV_DEV) leika-build-client

install-docs: ## Install the documentation toolchain (Sphinx, Furo, live reload)
	uv sync --locked --extra docs

test: ## Run Python unit tests
	$(UV_DEV) pytest --ignore=tests/e2e

test-e2e: ## Run Playwright browser tests
	$(UV_DEV) pytest tests/e2e -n auto

lint: ## Check Python formatting and lint rules
	$(UV_DEV) ruff check src tests examples scripts hatch_build.py sync_client_server.py
	$(UV_DEV) ruff format --check src tests examples scripts hatch_build.py sync_client_server.py

typecheck: ## Type-check the Python package and examples
	$(UV_DEV) pyright src examples

client-test: ## Type-check, lint, format-check, and unit-test the browser client
	cd src/leika/client && npm run typecheck && npm run lint && npm run format:check && npm test

build-client: ## Build the single-file browser client
	$(UV_DEV) leika-build-client

docs: ## Build the HTML documentation into docs/_build/html
	$(UV_DOCS) sphinx-build -b html -W --keep-going docs docs/_build/html

gallery: ## Regenerate the docs component gallery (screenshots + page)
	$(UV_DEV) python scripts/gallery.py

docs-serve: ## Serve the documentation on :8000, rebuilding as files change
	$(UV_DOCS) sphinx-autobuild -b html -W --keep-going docs docs/_build/html \
	  --watch README.md --open-browser

package: ## Build and validate the release distributions
	uv run --locked --extra dev --python 3.12 python scripts/build_release.py
