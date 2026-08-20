param()
Set-Location -Path (Join-Path $PSScriptRoot "..")
& ".venv\Scripts\python.exe" -m streamlit run cash_equivalents_mvp\ui\app.py
