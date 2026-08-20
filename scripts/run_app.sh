#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/Scripts/python.exe -m streamlit run cash_equivalents_mvp/ui/app.py
