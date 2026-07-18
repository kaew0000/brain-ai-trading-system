#!/bin/bash
echo "⚠️  Brain Bot V13 — LIVE TRADING (REAL MONEY)"
read -p "Type YES to confirm: " confirm
if [ "$confirm" != "YES" ]; then echo "Cancelled."; exit 1; fi
export EXECUTION_MODE=live
export BINANCE_TESTNET=false
python3 main.py
