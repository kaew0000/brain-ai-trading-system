@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Brain Bot V16 - LIVE TRADING  (canonical production launcher)
echo   WARNING: REAL MONEY AT RISK
echo ============================================================
echo.
echo   This is the ONLY supported launcher for live trading (Track
echo   W14-1 Item 11 consolidated run.bat and the old run_live.bat
echo   into this single file). It explicitly sets EXECUTION_MODE=live
echo   and BINANCE_TESTNET=false in THIS shell below, overriding
echo   whatever .env currently says -- a stale .env can never
echo   silently change what mode this actually runs in.
echo.
echo   Existing positions/orders are NOT touched by this launcher.
echo   Press Ctrl+C at any time to stop safely.
echo ============================================================
echo.

set /p confirm=Type YES to confirm LIVE trading with real funds:
if not "%confirm%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

REM Explicit, set here rather than only in .env -- see banner above.
set EXECUTION_MODE=live
set BINANCE_TESTNET=false

:loop
python main.py
if %ERRORLEVEL% EQU 0 (
    echo Bot exited cleanly.
    goto end
)
echo.
echo Bot crashed with exit code %ERRORLEVEL%.
choice /c YN /m "Restart bot in LIVE mode?"
if %ERRORLEVEL% EQU 2 goto end
timeout /t 5 /nobreak > nul
goto loop

:end
pause
