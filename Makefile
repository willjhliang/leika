.PHONY: help install build-client generate check-generated test test-e2e lint typecheck client-test docs docs-serve gallery package
E2E_WORKERS ?= 4


help: ## Show available development commands
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Leika and its development tools into the active environment
	python -m pip install -e ".[dev]"
	python src/leika/_client_autobuild.py

build-client: ## Build the single-file browser client if its sources changed
	python src/leika/_client_autobuild.py

generate: ## Regenerate the TypeScript protocol, version file and icon set
	python scripts/generate.py

check-generated: ## Fail if a generated file is out of date
	python scripts/generate.py --check

test: ## Run Python unit tests
	python -m pytest --ignore=tests/e2e

test-e2e: ## Run Playwright browser tests
	python -m pytest tests/e2e -n $(E2E_WORKERS)

lint: ## Check Python formatting and lint rules
	ruff check src tests examples scripts hatch_build.py
	ruff format --check src tests examples scripts hatch_build.py

typecheck: ## Type-check the Python package and examples
	pyright src examples

client-test: ## Type-check, lint, format-check, and unit-test the browser client
	cd src/leika/client && npm run typecheck && npm run lint && npm run format:check && npm test

docs: ## Build the HTML documentation into docs/_build/html
	python -m sphinx -b html -W --keep-going docs docs/_build/html

docs-serve: ## Serve the documentation on :8000, rebuilding as files change
	sphinx-autobuild -b html -W --keep-going docs docs/_build/html --watch README.md --open-browser

gallery: ## Regenerate the docs component gallery (screenshots + page)
	python scripts/gallery.py

package: ## Build and validate the release distributions
	python scripts/build_release.py
