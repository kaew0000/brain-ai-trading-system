@echo off
REM Builds dashboard_src\dist if missing (dist/ is gitignored, so a fresh
REM clone/zip has none -> api/app.py serves the legacy V13 FAKE-data demo).
REM Called by the run_*.bat launchers. Non-fatal: bot still starts if
REM Node.js is unavailable, but prints a clear warning.
setlocal
set "ROOT=%~dp0.."
if exist "%ROOT%\dashboard_src\dist\index.html" exit /b 0

where npm >nul 2>nul
if errorlevel 1 (
    echo [WARN] dashboard_src\dist not found and Node.js/npm is not installed.
    echo [WARN] Install Node.js LTS, then run: cd dashboard_src ^&^& npm ci ^&^& npm run build
    echo [WARN] Until then the LEGACY V13 demo dashboard ^(fake data^) is served.
    exit /b 0
)

echo [i] dashboard_src\dist missing - building V16 dashboard ^(one-time^)...
pushd "%ROOT%\dashboard_src"
call npm ci --no-audit --no-fund
call npm run build
popd
if not exist "%ROOT%\dashboard_src\dist\index.html" (
    echo [WARN] Dashboard build failed - legacy V13 demo ^(fake data^) will be served.
)
exit /b 0
