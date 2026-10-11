@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Chua co virtual environment. Chay setup.bat truoc.
    pause
    exit /b 1
)

echo [SYSTEM] Khoi dong he thong trong virtual environment...
venv\Scripts\python.exe main.py
pause
