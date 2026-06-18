@echo off
REM ============================================================
REM  科聪 KC Controller Simulator 启动脚本
REM  UDP 协议模拟器 — 模拟 MRC/FRC 控制器完整行为
REM
REM  自动激活 uv 虚拟环境并启动模拟器 + Web 仪表板
REM ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   KC Controller Simulator - 科聪 AGV 控制器模拟器
echo ============================================================
echo.

REM 检查 uv 虚拟环境是否存在
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] 首次运行, 正在创建 uv 虚拟环境...
    uv venv --python 3.12
    if errorlevel 1 (
        echo [ERROR] uv venv 创建失败, 请确认已安装 uv
        pause
        exit /b 1
    )
    echo [INFO] 正在安装依赖...
    uv pip install flask flask-socketio
    if errorlevel 1 (
        echo [ERROR] 依赖安装失败
        pause
        exit /b 1
    )
    echo [OK] 环境准备完成
    echo.
)

REM 激活虚拟环境
call .venv\Scripts\activate.bat

echo [INFO] 启动 AGV 模拟器...
echo   导航端口:     UDP :17804
echo   QR/变量端口:  UDP :17800
echo   Web 仪表板:   http://localhost:8080
echo   按 Ctrl+C 停止
echo.
python main.py --battery-drain 0 %*

pause
