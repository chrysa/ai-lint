PY ?= python3

# shared-standards: invariant target names, single entry point (run every task
# through `make <target>`, never invoke ruff/pytest/mypy/docker by hand).
.PHONY: help install lint format typecheck test cov docker-test build clean selfcheck check pre-commit

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install dev dependencies (from pyproject optional-deps)
	$(PY) -m pip install --upgrade pytest pytest-cov ruff mypy PyYAML

lint:  ## Ruff check + format verification (max 120 chars)
	$(PY) -m ruff check ai_lint.py ai-lint.py tests
	$(PY) -m ruff format --check ai_lint.py ai-lint.py tests

format:  ## Format with ruff
	$(PY) -m ruff format ai_lint.py ai-lint.py tests

typecheck:  ## Static type check (mypy)
	$(PY) -m mypy

test:  ## Run the test suite
	$(PY) -m pytest -q

cov:  ## Tests with coverage incl. CLI subprocesses (floor 60%, target 90%)
	rm -f .coverage .coverage.*
	COVERAGE_RUN=1 COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage run \
		--parallel-mode --rcfile=$(CURDIR)/pyproject.toml -m pytest -q
	COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage combine --rcfile=$(CURDIR)/pyproject.toml
	COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage report --rcfile=$(CURDIR)/pyproject.toml \
		--fail-under=60

docker-test:  ## Run the test suite in a container (shared-standards CI entry point)
	docker run --rm -v "$(CURDIR)":/w -w /w python:3.14-slim sh -c \
		"pip install -q pytest pytest-cov PyYAML && python -m pytest -q"

build:  ## Build the distributable (the single-file script needs no build; validate it)
	$(PY) -c "import ast; ast.parse(open('ai_lint.py').read()); print('ai_lint.py OK')"
	$(PY) ai-lint.py --version

selfcheck:  ## Run the tool on its own repo; fail only on real traces/secrets in-repo
	$(PY) tests/_selfcheck.py

pre-commit:  ## Run the full local gate (lint, types, tests, self-check)
	$(MAKE) lint typecheck test selfcheck

clean:  ## Remove caches and coverage artefacts
	rm -rf .coverage .coverage.* .ruff_cache .mypy_cache .pytest_cache htmlcov coverage.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

check: lint typecheck test  ## Lint, type-check, then test
