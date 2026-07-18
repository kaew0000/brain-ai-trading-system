@echo off
cd /d "%~dp0"
echo.
echo ================================================
echo   Brain Bot V13 - LIVE TRADING
echo   WARNING: REAL MONEY - USE WITH CAUTION
echo ================================================
echo.
set /p confirm=Type YES to confirm live trading: 
if not "%confirm%"=="YES" (
    echo Cancelled.
    pause
    exit /b
)
echo.
set EXECUTION_MODE=live
set BINANCE_TESTNET=false
python main.py
pause
