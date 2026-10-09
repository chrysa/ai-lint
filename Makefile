# prism-ai-lint Makefile.
# (No docker-compose: prism-ai-lint is a dependency-free Python tool run
# locally.) Conventions: invariant target names, single entry point (run
# every task through `make <target>`, never call ruff/pytest/mypy by hand),
# caches kept out of the source tree.

PY ?= python3
SOURCE := prism_ai_lint prism-ai-lint.py
TESTS := tests
REPORTS_DIR := .reports

# Keep tool caches out of the working tree.
export RUFF_CACHE_DIR := /tmp/prism-ai-lint-ruff-cache
export MYPY_CACHE_DIR := /tmp/prism-ai-lint-mypy-cache

.DEFAULT_GOAL := help

.PHONY: help install lint format typecheck type-check test cov \
        docker-test build clean selfcheck check ci ci-lint ci-test \
        pre-commit pre-commit-install pre-commit-update changelog

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install dev dependencies (from pyproject optional-deps)
	@$(PY) -m pip install --upgrade pytest pytest-cov ruff mypy PyYAML pre-commit

lint:  ## Ruff check + format verification (line length 120)
	@$(PY) -m ruff check $(SOURCE) $(TESTS)
	@$(PY) -m ruff format --check $(SOURCE) $(TESTS)

format:  ## Format with ruff
	@$(PY) -m ruff format $(SOURCE) $(TESTS)

typecheck:  ## Static type check (mypy)
	@$(PY) -m mypy

type-check: typecheck  ## Alias for typecheck

test:  ## Run the test suite
	@$(PY) -m pytest -q

cov:  ## Tests with coverage incl. CLI subprocesses (floor 60%, target 90%)
	@rm -f .coverage .coverage.*
	@mkdir -p $(REPORTS_DIR)
	@COVERAGE_RUN=1 COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage run \
		--parallel-mode --rcfile=$(CURDIR)/pyproject.toml -m pytest -q
	@COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage combine --rcfile=$(CURDIR)/pyproject.toml
	@COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage report --rcfile=$(CURDIR)/pyproject.toml \
		--fail-under=60
	@COVERAGE_FILE=$(CURDIR)/.coverage $(PY) -m coverage xml --rcfile=$(CURDIR)/pyproject.toml \
		-o $(REPORTS_DIR)/coverage.xml

selfcheck:  ## Run prism-ai-lint on its own repo; fail only on real traces/secrets in-repo
	@$(PY) tests/_selfcheck.py

build:  ## Validate the script parses and runs (no build step: dependency-free)
	@$(PY) -c "import ast; ast.parse(open('prism_ai_lint/_engine.py').read()); print('prism_ai_lint/_engine.py OK')"
	@$(PY) prism-ai-lint.py --version

docker-test:  ## Run the test suite in a container (CI parity)
	@docker run --rm -v "$(CURDIR)":/w -w /w python:3.14-slim sh -c \
		"pip install -q pytest pytest-cov PyYAML && python -m pytest -q"

pre-commit-install:  ## Install the pre-commit git hooks
	@pre-commit install

pre-commit:  ## Run all pre-commit hooks on all files
	@pre-commit run --all-files

pre-commit-update:  ## Update pinned pre-commit hook versions
	@pre-commit autoupdate

check: lint typecheck test  ## Lint, type-check, then test

# CI entry points.
ci-lint: lint typecheck  ## CI: static checks only
ci-test: test selfcheck  ## CI: tests + self-check
ci: lint typecheck test selfcheck  ## Full CI gate

changelog:  ## Regenerate CHANGELOG.md from Conventional Commits (git-cliff)
	@git cliff --output CHANGELOG.md

clean:  ## Remove caches and coverage artefacts
	@rm -rf .coverage .coverage.* $(REPORTS_DIR) htmlcov coverage.json
	@rm -rf "$(RUFF_CACHE_DIR)" "$(MYPY_CACHE_DIR)" .ruff_cache .mypy_cache .pytest_cache .benchmarks
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
