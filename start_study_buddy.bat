@echo off
echo ========================================================
echo        Starting AI Study Buddy (WSL + Windows Host)
echo ========================================================

echo 1. Verifying and updating requirements inside WSL...
wsl python3 -m pip install --user --break-system-packages -r requirements.txt

echo 2. Launching FastAPI Server inside WSL (Port 7860)...
start "Study Buddy Server (WSL)" cmd /k "wsl python3 -u server.py"

echo 3. Waiting 5 seconds for server to start...
powershell -Command "Start-Sleep -s 5"

echo 4. Launching Windows Watchdog Client (Host)...
start "Study Buddy Watchdog (Windows)" cmd /k ".\venv\Scripts\python -u win_watchdog.py"

echo 5. Opening Focus Dashboard in Web Browser...
start http://localhost:7860/

echo ========================================================
echo All systems successfully launched!
echo - You can view server logs in the "Study Buddy Server" window.
echo - You can view window tracking logs in the "Study Buddy Watchdog" window.
echo ========================================================
powershell -Command "Start-Sleep -s 3"
exit
