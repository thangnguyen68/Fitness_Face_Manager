@echo off
setlocal
cd /d "%~dp0"
echo [1/2] Tao moi truong Python...
if not exist "backend\.venv\Scripts\python.exe" python -m venv backend\.venv
if errorlevel 1 exit /b 1
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 exit /b 1
echo [2/2] Cai dat frontend...
cd frontend
npm install
if errorlevel 1 exit /b 1
echo Hoan tat. Chay run.cmd de mo website.
