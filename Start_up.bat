@echo off
setlocal
title Shunguang Companion - Backend Logs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-console.ps1"
set "launch_exit=%ERRORLEVEL%"
if not "%launch_exit%"=="0" pause
exit /b %launch_exit%
