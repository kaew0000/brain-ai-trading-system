@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo   Brain Bot BTCUSDT Futures - LIVE TRADING
echo ============================================================
echo.
echo   [!] WARNING: LIVE MODE - REAL MONEY AT RISK
echo   [!] Make sure .env is configured correctly.
echo   [!] Ensure BINANCE_TESTNET=false in .env
echo.
echo   Press Ctrl+C at any time to stop safely.
echo ============================================================

choice /c YN /m "Continue with LIVE trading?"
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
