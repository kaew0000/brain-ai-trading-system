@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo   Brain Bot BTCUSDT Futures - Dev/Test Launcher
echo ============================================================
echo.
echo   [i] Runs with whatever EXECUTION_MODE/BINANCE_TESTNET is
echo       currently set in .env (paper/testnet by default).
echo   [!] For LIVE trading with real funds, use run_live.bat instead
echo       -- it sets LIVE mode explicitly rather than trusting .env,
echo       and requires a separate typed confirmation.
echo.
echo   Press Ctrl+C at any time to stop safely.
echo ============================================================

choice /c YN /m "Continue?"
if %ERRORLEVEL% EQU 2 (
    echo Cancelled.
    exit /b 0
)

cd /d "%~dp0"

:loop
python main.py
if %ERRORLEVEL% EQU 0 (
    echo Bot exited cleanly.
    goto end
)
echo.
echo Bot crashed with exit code %ERRORLEVEL%.
choice /c YN /m "Restart bot?"
if %ERRORLEVEL% EQU 2 goto end
timeout /t 5 /nobreak > nul
goto loop

:end
pause
