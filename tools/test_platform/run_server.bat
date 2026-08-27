@echo off
REM Launch the test platform (uses the workspace .venv) -> http://127.0.0.1:5300
REM NOTE: keep this file pure ASCII. Non-ASCII bytes (e.g. Chinese comments) mixed
REM with LF-only line endings previously desynced cmd.exe's DBCS line parser on
REM Traditional Chinese Windows (cp950), scrambling the whole script when double
REM clicked (found 2026-08-26). Put any Chinese explanation in the docs, not here.
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo .venv not found. Run: powershell -File scripts\setup_test_env.ps1
  exit /b 1
)
set PYTHONUTF8=1
REM Open the browser a couple seconds after launch, once Flask has bound the port.
REM Runs detached so it doesn't block the foreground server process below.
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:5300"
"%PY%" "%HERE%web_ui\app.py"
endlocal
