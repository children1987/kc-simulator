@echo off
REM ============================================================
REM  KC Simulator 一键启动脚本
REM  启动模拟器并运行端到端模拟
REM ============================================================

echo ============================================
echo   KC Simulator - 端到端模拟
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查依赖
pip show flask >nul 2>&1
if errorlevel 1 (
    echo [INFO] 安装依赖...
    pip install -r requirements.txt -q
)

REM 停止已有的模拟器
taskkill /F /IM python.exe >nul 2>&1

echo [1/2] 启动科聪模拟器...
start /B python main.py --no-dashboard

REM 等待模拟器启动
echo [INFO] 等待模拟器启动...
timeout /t 3 /nobreak >nul

REM 检查端口
netstat -an | findstr "17804" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 模拟器启动失败，端口 17804 未监听
    pause
    exit /b 1
)
echo [OK] 模拟器已启动

echo.
echo [2/2] 启动端到端模拟...
echo ============================================
echo.
python simulate_e2e.py

echo.
echo ============================================
echo [OK] 模拟完成
echo ============================================
pause
