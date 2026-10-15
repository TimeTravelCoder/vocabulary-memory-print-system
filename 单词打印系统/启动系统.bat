@echo off
chcp 65001 >nul
cd /d "%~dp0"
title A4 单词记忆本·字帖打印系统

echo 正在启动 A4 单词记忆本打印系统...
echo 服务启动后将自动在浏览器中打开系统界面。
echo 如需关闭服务，请直接关闭本命令窗口或按 Ctrl + C。
echo.

where python >nul 2>nul
if %errorlevel% equ 0 (
    python server.py
    goto end
)

if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
    "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" server.py
    goto end
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py server.py
    goto end
)

echo.
echo [ERROR] Python environment not detected.
echo Please install Python or ensure it is added to your PATH environment variable.
echo.
pause

:end
