@echo off
setlocal
chcp 65001 >nul
title Shunguang Companion - Installation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
set "install_exit=%ERRORLEVEL%"
if not defined SHUNGUANG_INSTALL_NO_PAUSE pause
exit /b %install_exit%
