@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] Tao virtual environment (ke thua thu vien he thong)...
python -m venv venv --system-site-packages
if errorlevel 1 ( echo [ERROR] Khong tao duoc venv & pause & exit /b 1 )

echo [2/2] Cai silero-vad...
venv\Scripts\pip.exe install silero-vad
if errorlevel 1 ( echo [ERROR] Cai silero-vad that bai & pause & exit /b 1 )

echo.
echo [DONE] Cai dat hoan tat!
echo Yeu cau: PyQt5, torch, sherpa-onnx, numpy, sounddevice, huggingface-hub, pyserial
echo phai duoc cai o Python goc (global).
echo.
echo Chay run.bat de khoi dong he thong.
pause
