#!/usr/bin/env bash
# There is no standalone worker daemon in this MVP — see scripts/run_worker.ps1's comment header
# and docs/architecture.md for why. This script executes one run to completion.
#
# Usage: ./scripts/run_worker.sh run_xxxxxxxxxxxx
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -z "${1:-}" ]; then
    echo "Usage: $0 <run_id>" >&2
    exit 1
fi
.venv/Scripts/python.exe -m cash_equivalents_mvp.cli execute --run-id "$1"
