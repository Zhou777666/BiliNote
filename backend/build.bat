@echo off
setlocal
cd /d "%~dp0.."
if errorlevel 1 exit /b 1
python backend\build_backend.py %*
exit /b %errorlevel%
