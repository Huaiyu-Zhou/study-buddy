@echo off
title Study Buddy Watchdog (Interactive)
echo ========================================================
echo   Starting Study Buddy Watchdog Client in User Session
echo ========================================================
cd /d "C:\Users\huaiy\OneDrive\Desktop\study-buddy"
.\venv\Scripts\python -u win_watchdog.py
echo ========================================================
echo Watchdog client stopped.
pause
