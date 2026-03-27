@echo off
TITLE SportsCaster Pro
SET ROOT=%~dp0

IF EXIST "%ROOT%venv\Scripts\python.exe" (SET PY="%ROOT%venv\Scripts\python.exe") ELSE (SET PY=python)

echo.
echo ================================================
echo   SportsCaster Pro
echo   Single server on port 8000
echo ================================================
echo.
START "SportsCaster" cmd /k "cd /d %ROOT%backend && %PY% -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 4 /nobreak >nul
start http://localhost:8000
echo.
echo Open: http://localhost:8000   Login: admin / admin
echo For WiFi: run ipconfig, find IPv4 address, use http://YOUR-IP:8000
echo.
pause
