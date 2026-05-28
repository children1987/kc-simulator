@echo off
echo ============================================
echo   KC Simulator - End-to-End Simulation
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

taskkill /F /IM python.exe >nul 2>&1

echo [1/2] Starting simulator...
start /B python main.py --no-dashboard
timeout /t 3 /nobreak >nul

netstat -an | findstr "17804" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Simulator failed to start
    pause
    exit /b 1
)
echo [OK] Simulator running

echo.
echo [2/2] Running simulation...
echo ============================================
echo.
python simulate_e2e.py

echo.
echo ============================================
echo [OK] Done
echo ============================================
pause
