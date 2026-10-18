@echo off
setlocal
cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
  echo Chua cai dat. Hay chay setup.cmd truoc.
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo Chua cai dat frontend. Hay chay setup.cmd truoc.
  exit /b 1
)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Da tao .env tu mau. Hay doi JWT_SECRET va mat khau truoc khi dung du lieu that.
)
for /f "usebackq tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
start "FaceAccess API" cmd /k "cd /d backend && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
start "FaceAccess Web" cmd /k "cd /d frontend && npm run dev"
echo API: http://localhost:8000/docs
echo Website: http://localhost:5173
