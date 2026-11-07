.PHONY: install check lint test eval examples

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .
	mypy

test:
	pytest --cov --cov-report=term-missing --cov-fail-under=90

check: lint test

# Needs SFM_SOURCE_DSN: a scratch PostgreSQL database for the validation scenarios.
eval:
	sfmigrate eval --check --require-validation --report eval-report.md

examples:
	rm -rf docs/examples
	sfmigrate translate examples/legacy --out docs/examples
