@echo off
TITLE SportsCaster Pro v2
SET ROOT=%~dp0

REM Find venv python
IF EXIST "%ROOT%venv\Scripts\python.exe" (
    SET PY=%ROOT%venv\Scripts\python.exe
) ELSE (
    SET PY=python
)

echo Starting SportsCaster Pro v2...
START "Backend"  cmd /k "cd /d %ROOT%backend && "%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 2 /nobreak >nul
START "Frontend" cmd /k "cd /d %ROOT%frontend && "%PY%" -m http.server 3000"
timeout /t 1 /nobreak >nul
start http://localhost:3000
echo Open: http://localhost:3000  Login: admin/admin
