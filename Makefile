PY ?= python3

.PHONY: help test lint fmt check selfcheck cov typecheck

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

test:  ## Run the test suite
	$(PY) -m pytest -q

lint:  ## Lint (ruff check) and verify formatting (max 100 chars)
	$(PY) -m ruff check claude_lint.py claude-lint.py tests
	$(PY) -m ruff format --check claude_lint.py claude-lint.py tests

fmt:  ## Format with ruff
	$(PY) -m ruff format claude_lint.py claude-lint.py tests

selfcheck:  ## Run the tool on its own repo; fail only on real traces/secrets in-repo
	$(PY) tests/_selfcheck.py

cov:  ## Test with coverage (target >= 90%)
	$(PY) -m pytest --cov --cov-report=term-missing --cov-fail-under=90

typecheck:  ## Static type check (mypy strict)
	$(PY) -m mypy

check: lint test  ## Lint then test
