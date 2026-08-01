@echo off
REM ============================================================
REM build.bat
REM ==========
REM Builds DoctorVoiceNotes.exe from source using build.spec.
REM
REM Run this from the project root (the folder containing main.py):
REM     build.bat
REM ============================================================

setlocal enabledelayedexpansion

echo ===================================================
echo  Doctor Voice Notes - Windows Build Script (Phase 7)
echo ===================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    echo        Install Python 3.12 x64 from python.org, make sure
    echo        "Add python.exe to PATH" is checked during install,
    echo        then re-run this script.
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Using Python %PYVER%
echo.

if not exist venv (
    echo Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create the virtual environment.
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo Installing dependencies from requirements.txt ...
pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. See the output above.
    echo        A common cause: ctranslate2/faster-whisper wheels do
    echo        not exist for very new Python versions. This project
    echo        targets Python 3.12 specifically - see PRD Section 9.
    exit /b 1
)
echo.

if not exist "models\small.en\model.bin" (
    echo ============================================================
    echo  WARNING: models\small.en\model.bin was not found.
    echo.
    echo  The build will still complete, but DoctorVoiceNotes.exe will
    echo  show a fatal error on its very first launch until the model
    echo  is downloaded. See models\small.en\README_DOWNLOAD_MODEL.txt
    echo  for exact download/conversion steps. You can build now and
    echo  add the model to dist\DoctorVoiceNotes\models\small.en\
    echo  afterwards instead, if you prefer.
    echo ============================================================
    echo.
)

if not exist "assets\icons\app_icon.ico" (
    echo ERROR: assets\icons\app_icon.ico is missing.
    echo        build.spec references this file directly and will fail
    echo        without it, even as a placeholder. See README.md,
    echo        section "Application icon".
    exit /b 1
)

echo Cleaning previous build output ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

echo Running PyInstaller (this can take a few minutes) ...
pyinstaller build.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See the output above.
    exit /b 1
)
echo.

echo Copying the speech model into the built app folder ...
if exist "models\small.en" (
    xcopy /e /i /y "models\small.en" "dist\DoctorVoiceNotes\models\small.en" >nul
) else (
    mkdir "dist\DoctorVoiceNotes\models\small.en" 2>nul
)

echo.
echo ===================================================
echo  BUILD COMPLETE
echo ===================================================
echo  Output folder: dist\DoctorVoiceNotes\
echo  Executable:    dist\DoctorVoiceNotes\DoctorVoiceNotes.exe
echo.
echo  NEXT STEP - DO NOT SKIP:
echo  Before building the installer, run DoctorVoiceNotes.exe directly
echo  from dist\DoctorVoiceNotes\ and confirm it launches normally.
echo  build.spec has a "KNOWN OPEN RISK" note about a crash that was
echo  found (and NOT fully resolved) during Linux sandbox testing -
echo  this is the first real chance to find out whether it affects
echo  Windows too. See TEST_CHECKLIST.md for the full procedure.
echo ===================================================

endlocal