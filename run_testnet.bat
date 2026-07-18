@echo off
cd /d "%~dp0"
echo.
echo ================================================
echo   Brain Bot V13 - TESTNET MODE
echo   Binance Testnet (fake money, real API)
echo   Dashboard opens at http://localhost:8000
echo ================================================
echo.
set EXECUTION_MODE=testnet
set BINANCE_TESTNET=true
python main.py
pause
