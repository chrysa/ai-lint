PY ?= python3

.PHONY: help test lint fmt check selfcheck

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

test:  ## Run the test suite
	$(PY) -m pytest -q

lint:  ## Lint the linter and its tests with ruff
	$(PY) -m ruff check agent-config-lint.py tests

fmt:  ## Format with ruff
	$(PY) -m ruff format agent-config-lint.py tests

selfcheck:  ## Run the tool on its own repo (no attribution, no secrets)
	$(PY) agent-config-lint.py . --no-cli --no-history --no-scaffold --strict --lang en

check: lint test  ## Lint then test
