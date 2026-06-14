@echo off
title FormOCR Setup
cd /d "%~dp0"
echo.
echo  FormOCR Offline Installer
echo  =========================
echo  This will install FormOCR, copy models, and warm the OCR engine (several minutes).
echo  After setup, the app opens immediately with no startup wait.
echo  Install location: %LOCALAPPDATA%\Programs\FormOCR
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-formocr.ps1" -SourceDir "%~dp0app" -LaunchAfter
if errorlevel 1 (
  echo.
  echo Setup failed. See messages above.
  pause
  exit /b 1
)
echo.
pause
