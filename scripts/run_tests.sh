#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p local_data/test_results

.venv/Scripts/python.exe -m ruff check cash_equivalents_mvp
.venv/Scripts/python.exe -m mypy cash_equivalents_mvp
.venv/Scripts/python.exe -m pytest tests/ -q \
    --junitxml=local_data/test_results/junit.xml \
    --cov=cash_equivalents_mvp --cov-report=term-missing --cov-report=xml:local_data/test_results/coverage.xml
.venv/Scripts/python.exe scripts/generate_test_summary.py
