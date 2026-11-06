@echo off
cd /d "%~dp0"
python --version
if errorlevel 1 goto fail
python -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
if not exist .env copy .env.example .env >nul
echo Setup complete. Edit .env before running start.cmd.
pause
exit /b 0
:fail
echo Setup failed. Check Python 3.10+ and internet connection.
pause
exit /b 1
