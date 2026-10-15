@echo off
chcp 65001 >nul
title 单词记忆打印系统 - Vocabulary Memory Print System
echo ========================================================
echo  正在启动 单词记忆打印系统 (Vocabulary Print System)...
echo ========================================================
cd /d "%~dp0单词打印系统"
python server.py
pause
