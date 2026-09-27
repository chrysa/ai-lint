PY ?= python3

.PHONY: test lint fmt check

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check agent-config-lint.py tests

fmt:
	$(PY) -m ruff format agent-config-lint.py tests

check: lint test
