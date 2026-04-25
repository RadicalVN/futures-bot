@echo off
title Binance Trading Bot
cd /d "%~dp0"

echo [1/3] Kiem tra moi truong ao venv...
if not exist "venv\Scripts\python.exe" (
    echo.
    echo [*] Dang tao venv lan dau chi mat 1-2 phut...
    python -m venv venv
    echo [*] Dang cai dat thu vien...
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo [2/3] Moi truong san sang.
echo [3/3] Dang khoi dong Bot...
echo =======================================================
venv\Scripts\python.exe main.py

pause