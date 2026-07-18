@echo off
cd /d "%~dp0"
echo.
echo ================================================
echo   Brain Bot V13 - PAPER TRADING MODE
echo   No real orders - Safe to test
echo   Dashboard opens at http://localhost:8000
echo ================================================
echo.
set EXECUTION_MODE=paper
set BINANCE_TESTNET=true
python main.py
pause
