#!/bin/sh
set -eu
cd "$(dirname "$0")"
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
