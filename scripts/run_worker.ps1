# There is no standalone worker daemon in this MVP — background execution happens via a
# ThreadPoolExecutor inside the same process as the UI/CLI caller (orchestration/worker.py),
# per the documented decision in docs/architecture.md. This script is the CLI-driven equivalent:
# it executes one run to completion, which is what a "worker" would do in a queue-based deployment.
#
# Usage: .\scripts\run_worker.ps1 -RunId run_xxxxxxxxxxxx
param(
    [Parameter(Mandatory = $true)][string]$RunId
)
Set-Location -Path (Join-Path $PSScriptRoot "..")
& ".venv\Scripts\python.exe" -m cash_equivalents_mvp.cli execute --run-id $RunId
