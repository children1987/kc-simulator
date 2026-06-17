@echo off
echo ============================================
echo   KC Simulator + openTCS End-to-End Setup
echo ============================================
echo.

uv --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found — install via: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

set OPENTCS_HOME=%~dp0..\..\opentcs-7.2.1-bin

echo [1/3] Starting KC Simulator...
taskkill /F /IM python.exe >nul 2>&1
start "KC-Simulator" uv run python main.py
timeout /t 3 /nobreak >nul

netstat -an | findstr "17804" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Simulator failed to start on port 17804
    pause
    exit /b 1
)
echo [OK] KC Simulator running (UDP :17804)

echo.
echo [2/3] Starting openTCS Kernel...
if exist "%OPENTCS_HOME%\opentcs-kernel\startKernel.bat" (
    start "openTCS-Kernel" cmd /c "cd /d "%OPENTCS_HOME%\opentcs-kernel" && startKernel.bat"
    echo [OK] openTCS Kernel starting...
    timeout /t 10 /nobreak >nul
) else (
    echo [WARN] openTCS not found at %OPENTCS_HOME%
    echo        Please start openTCS Kernel manually
)

echo.
echo [3/3] Checking connection...
netstat -an | findstr "1099" >nul 2>&1
if errorlevel 1 (
    echo [WARN] openTCS RMI port 1099 not listening yet
    echo        Kernel may still be starting, please wait...
) else (
    echo [OK] openTCS Kernel running (RMI :1099)
)

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo   Next steps:
echo   1. Open Operations Desk
echo   2. File > Load model > select kc-demo
echo   3. Actions > New transport order
echo   4. Add drive orders (pick locations)
echo   5. Click Ok to dispatch
echo.
echo   The AGV will move in the simulator!
echo ============================================
pause
