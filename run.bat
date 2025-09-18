@echo off
setlocal
REM --- use UTF-8 so Chinese logs don't garble ---
chcp 65001 >nul

REM --- always run from this .bat's folder ---
cd /d "%~dp0"

echo [INFO] Preparing Python virtual environment...

REM --- create venv if missing ---
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Creating venv...
    py -3 -m venv venv 2>nul || python -m venv venv
    if errorlevel 1 (
        echo [ERR] Python not found. Please install Python 3.9+ and add it to PATH.
        pause
        exit /b 1
    )
)

set "PYEXE=%~dp0venv\Scripts\python.exe"

REM --- upgrade pip (first run may take a bit) ---
"%PYEXE%" -m pip install --upgrade pip

REM --- install deps; comment these two lines out after first success to speed up ---
"%PYEXE%" -m pip install -r requirements.txt

REM --- Qt HiDPI settings to reduce warnings and make UI crisp ---
set QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough
set QT_AUTO_SCREEN_SCALE_FACTOR=1
set QT_ENABLE_HIGHDPI_SCALING=1

echo [INFO] Starting UI...
"%PYEXE%" -u bot_fluent.py

echo.
echo [INFO] Process finished.
pause
