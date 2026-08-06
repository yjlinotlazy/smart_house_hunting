.PHONY: setup dev build run test lint format format-check privacy-check verify clean

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'
	npm --prefix frontend install

dev:
	.venv/bin/python scripts/dev.py

build:
	npm --prefix frontend run build

run: build
	.venv/bin/smart-house-hunting

test:
	.venv/bin/pytest
	npm --prefix frontend test

lint:
	.venv/bin/ruff check .
	npm --prefix frontend run lint

format:
	.venv/bin/ruff format .
	npm --prefix frontend run format:write

format-check:
	.venv/bin/ruff format --check .
	npm --prefix frontend run format

verify: lint format-check test build

privacy-check:
	.venv/bin/python scripts/check_privacy.py

clean:
	.venv/bin/python -c 'import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ("frontend/dist", ".pytest_cache", ".ruff_cache")]; print("build caches removed")'
