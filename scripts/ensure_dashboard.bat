@echo off
REM Makes sure dashboard_src\dist is a current build of the V16 dashboard.
REM dist/ is gitignored, so a fresh clone/zip has none (api/app.py then serves
REM the legacy V13 FAKE-data demo) and, after `git pull`, an OLD build keeps
REM being served until it is rebuilt. This launcher helper therefore builds when
REM dist is MISSING (PR #116) or STALE (sources newer than dist\index.html).
REM
REM Called by the run_*.bat launchers. Non-fatal: the bot still starts if
REM Node.js is unavailable or the build fails, but a clear warning is printed.
REM
REM Opt-out of the stale check (missing-dist build still happens):
REM     set BRAIN_DASHBOARD_AUTOREBUILD=0
setlocal EnableExtensions
set "ROOT=%~dp0.."
set "DASH=%ROOT%\dashboard_src"
set "DIST_INDEX=%DASH%\dist\index.html"

if exist "%DIST_INDEX%" if "%BRAIN_DASHBOARD_AUTOREBUILD%"=="0" exit /b 0

REM Ask the helper (scripts\dashboard_build_state.py, stdlib-only) what to do.
set "STATE="
for /f "usebackq delims=" %%S in (`python "%~dp0dashboard_build_state.py" "%DASH%" 2^>nul`) do set "STATE=%%S"

if /i "%STATE%"=="fresh" exit /b 0
if /i "%STATE%"=="build" goto :need_build
if /i "%STATE%"=="install_build" goto :need_build

REM Helper unavailable / unknown answer -> legacy behaviour: build only if missing.
if exist "%DIST_INDEX%" exit /b 0
set "STATE=install_build"

:need_build
where npm >nul 2>nul
if errorlevel 1 (
    echo [WARN] Dashboard needs a build but Node.js/npm is not installed.
    echo [WARN] Install Node.js LTS, then run: cd dashboard_src ^&^& npm ci ^&^& npm run build
    if not exist "%DIST_INDEX%" echo [WARN] Until then the LEGACY V13 demo dashboard ^(fake data^) is served.
    if exist "%DIST_INDEX%" echo [WARN] Until then the OLD dashboard build is served ^(may lack newer pages/fixes^).
    exit /b 0
)

REM Keep the previous build so a failed rebuild cannot leave only the fake demo.
set "BAK=%TEMP%\brain_dashboard_dist_backup"
set "HAVE_BAK="
if exist "%DIST_INDEX%" (
    if exist "%BAK%" rmdir /s /q "%BAK%"
    xcopy "%DASH%\dist" "%BAK%\" /E /I /Q /Y >nul
    if not errorlevel 1 set "HAVE_BAK=1"
)

echo [i] Dashboard build is %STATE% - rebuilding V16 dashboard...
pushd "%DASH%"
if /i "%STATE%"=="install_build" call npm ci --no-audit --no-fund
call npm run build
set "BUILD_RC=%ERRORLEVEL%"
popd

if not exist "%DIST_INDEX%" (
    if defined HAVE_BAK (
        xcopy "%BAK%" "%DASH%\dist\" /E /I /Q /Y >nul
        echo [WARN] Dashboard build failed - restored the previous build.
    ) else (
        echo [WARN] Dashboard build failed - legacy V13 demo ^(fake data^) will be served.
    )
    exit /b 0
)
if not "%BUILD_RC%"=="0" echo [WARN] Dashboard build reported errors ^(exit %BUILD_RC%^) - serving the available build.
exit /b 0
