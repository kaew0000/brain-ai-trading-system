@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo   Brain Bot BTCUSDT Futures - Windows Setup
echo ============================================================
echo.

REM ── Check Python ────────────────────────────────────────────
python --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found.
    echo         Install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo Found: %%i

REM ── Check Git ───────────────────────────────────────────────
git --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Git not found. Vendor repo cloning will be skipped.
    echo           Install from https://git-scm.com/
) else (
    for /f "tokens=*" %%i in ('git --version') do echo Found: %%i
)

echo.
echo Running installer...
echo.

REM ── Run install.py ──────────────────────────────────────────
python "%~dp0install.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed. Check output above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup complete!
echo   Edit .env with your Binance API keys, then run:
echo     run_testnet.bat   (paper trading - safe)
echo     run.bat           (live trading - real money)
echo ============================================================
pause
