# KC Controller Simulator — 科聪 MRC/FRC 控制器模拟器

[![CI](https://github.com/children1987/kc-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/children1987/kc-simulator/actions/workflows/ci.yml)

在**不连接真实硬件控制器**的情况下，模拟科聪 MRC/FRC 控制器的 UDP 协议行为，用于验证 openTCS 上位机调度系统的完整链路。

## 目录

- [快速开始](#快速开始)
- [启动方式详解](#启动方式详解)
  - [方式一：直接启动（推荐调试用）](#方式一直接启动推荐调试用)
  - [方式二：一键启动整套环境](#方式二一键启动整套环境)
  - [方式三：自定义参数启动](#方式三自定义参数启动)
- [命令行参数](#命令行参数)
- [Web 仪表板](#web-仪表板)
- [地图配置](#地图配置)
- [辅助脚本](#辅助脚本)
- [与 openTCS 配合使用](#与-opentcs-配合使用)
- [项目文件说明](#项目文件说明)

---

## 环境要求

- **[uv](https://docs.astral.sh/uv/)** — Python 包管理器（自动管理虚拟环境和依赖）
- Windows / Linux / macOS

```bash
# 安装 uv（如未安装）
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 快速开始

```bash
cd E:\workspace\opentcs\simulators\kc-simulator

# uv 自动创建虚拟环境、安装依赖、启动模拟器（一条命令）
uv run python main.py
```

首次运行时会自动下载 Python 3.12 并安装所有依赖，之后直接启动。

启动后输出类似：

```
============================================================
  KC Controller Simulator V1.0
  科聪 MRC/FRC 控制器 UDP 协议模拟器
============================================================
  导航端口:     17804
  QR/变量端口:  17800
  授权码:       KC-SIMULATOR-01
  地图文件:     E:\workspace\opentcs\simulators\kc-simulator\map_config.json
  AGV 速度:     1.0 m/s
  每步耗电:     1%
  Web 仪表板:   http://localhost:8080
============================================================
[OK] UDP 服务器已启动，等待 openTCS 连接...
[OK] Web 仪表板已启动: http://localhost:8080
```

浏览器访问 [http://localhost:8080](http://localhost:8080) 可查看实时 AGV 状态和通信日志。

---

## 启动方式详解

### 方式一：直接启动（推荐调试用）

**适用场景**：你手动启动了 openTCS Kernel 和 Operations Desk，只需要模拟器。

```bash
cd E:\workspace\opentcs\simulators\kc-simulator
uv run python main.py
```

模拟器会监听两个 UDP 端口：
| 端口 | 用途 |
|------|------|
| `17804` | 导航指令（路径下发、状态查询） |
| `17800` | QR/变量操作（读写控制器变量、举升控制） |

### 方式二：一键启动整套环境

**适用场景**：你想要一次性启动模拟器 + openTCS Kernel，快速搭建完整调试环境。

```bash
# 双击或在终端运行
run.bat
```

该脚本自动执行：
1. 杀掉已有的 Python 进程，启动 KC Simulator
2. 验证 UDP 端口 17804 已监听
3. 启动 openTCS Kernel（`opentcs-kernel/startKernel.bat`）
4. 检查 RMI 端口 1099 是否就绪

> **注意**：`run.bat` 假设 openTCS 安装在 `simulators/../../opentcs-7.2.1-bin/`（即 `E:\workspace\opentcs\opentcs-7.2.1-bin\`）。如果路径不对，请编辑 `run.bat` 中的 `OPENTCS_HOME` 变量。

### 方式三：自定义参数启动

所有端口、地图、授权码均可通过命令行覆盖：

```bash
# 使用非默认端口
uv run python main.py --nav-port 17805 --qr-port 17801 --dashboard-port 9090

# 使用自定义地图文件
uv run python main.py --map my_custom_map.json

# 指定授权码（需与 openTCS 端一致）
uv run python main.py --auth-code MY_CUSTOM_AUTH

# 调高 AGV 移动速度（调试时可加速）
uv run python main.py --max-speed 2.0

# 关闭电量消耗（调试时避免因低电量中断）
uv run python main.py --battery-drain 0
```

---

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--nav-port` | `17804` | 导航指令 UDP 端口 |
| `--qr-port` | `17800` | QR/变量操作 UDP 端口 |
| `--dashboard-port` | `8080` | Web 仪表板 HTTP 端口 |
| `--dashboard-host` | `0.0.0.0` | 仪表板绑定地址 |
| `--map` | `map_config.json` | 地图配置文件路径 |
| `--auth-code` | `KC-SIMULATOR-01` | UDP 协议授权码（16 字节 ASCII） |
| `--max-speed` | `1.0` | AGV 最大移动速度（m/s） |
| `--battery-drain` | `0.01` | 每到达一个点消耗的电量比例（设为 `0` 不耗电） |

---

## Web 仪表板

启动后访问 `http://localhost:8080`，提供：

- **实时 AGV 位置**：在地图上可视化当前坐标、朝向、速度
- **状态面板**：工作模式、AGV 状态、订单 ID、电量、货物状态、定位状态
- **通信日志**：实时展示 UDP 收发数据包（方向、地址、命令码、原始 hex）
- **快捷操作**：
  - 暂停/恢复/取消任务
  - 装货/卸货（模拟举升）
  - 注入错误码（测试异常处理）
  - 充满电量

---

## 地图配置

地图由 JSON 文件定义（默认 `map_config.json`），包含点位和路径：

```json
{
  "points": [
    { "id": 0, "x": 0, "y": 0, "name": "00" },
    { "id": 1, "x": 2, "y": 0, "name": "01" }
  ],
  "paths": [
    { "id": 1, "from": 0, "to": 1 },
    { "id": 2, "from": 1, "to": 0 }
  ]
}
```

- **points**：地图上的停靠点，`id` 与 openTCS 模型中的 point name 对应
- **paths**：点与点之间的有向路径

如果指定的地图文件不存在，模拟器会自动生成一个 10 点的默认直线地图。

> **重要**：地图点位 ID 必须与 openTCS 模型文件（`model.xml`）中的 point 名称一致，否则路径下发会失败。

---

## 辅助脚本

| 脚本 | 说明 |
|------|------|
| `run.bat` | 一键启动模拟器 + openTCS Kernel |
| `charge.bat` | 通过仪表板 API 将 AGV 电量充至 100% |

---

## 与 openTCS 配合使用

### 完整调试流程

```
┌─────────────┐    UDP :17804    ┌──────────────┐    RMI :1099    ┌───────────────┐
│ KC Simulator │◄────────────────►│  openTCS      │◄──────────────►│ Operations     │
│ (Python)     │    UDP :17800    │  Kernel (Java)│                │ Desk (Java)   │
│ :8080 Web UI │                  │  + Adapter    │                │               │
└──────────────┘                  └──────────────┘                └───────────────┘
```

1. **启动模拟器**：`uv run python main.py`
2. **启动 openTCS Kernel**：运行 `opentcs-7.2.1-bin/opentcs-kernel/startKernel.bat`
3. **启动 Operations Desk**：运行 `opentcs-7.2.1-bin/opentcs-kernelcontrolcenter/startKCC.bat`
4. **加载模型**：File → Load model → 选择对应的 `model.xml`
5. **下发运输单**：创建 Transport Order，选择起点和终点
6. **观察执行**：在 Web 仪表板 (`:8080`) 查看 AGV 移动和通信日志

### 关键注意点

- 适配器的授权码必须与模拟器一致（默认 `KC-SIMULATOR-01`）
- 地图点位 ID 必须匹配 openTCS 模型中的 point 名称
- 如果出现连接问题，先用 `tools/kc-tools/kc-inspect.py` 直连模拟器验证 UDP 通信是否正常

---

## 项目文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主入口，解析命令行参数，启动 UDP 服务器和 Web 仪表板 |
| `udp_server.py` | UDP 服务器核心，监听 17804/17800 端口，处理协议帧 |
| `agv_engine.py` | 虚拟 AGV 运动引擎，模拟位置更新、路径跟踪、电量消耗 |
| `protocol.py` | 科聪 UDP 协议编解码（帧格式、命令码、状态结构体） |
| `dashboard.py` | Flask + SocketIO Web 仪表板后端 |
| `templates/index.html` | Web 仪表板前端页面 |
| `map_config.json` | 地图配置文件（点位 + 路径） |
| `agv_driver.py` | AGV 驱动逻辑 |
| `simulate_e2e.py` | 端到端协议测试脚本（不依赖 openTCS） |
| `opentcs_bridge.py` | openTCS REST API 桥接（下发运输单） |
| `create_transport_order.py` | 通过 REST API 创建运输单的 Python 脚本 |
| `extract_doc.py` | 从协议文档提取命令码定义 |
| `pyproject.toml` | 项目元数据与依赖声明（uv 使用） |
| `.python-version` | 固定 Python 版本为 3.12 |
| `uv.lock` | 依赖锁文件，确保可复现安装 |
| `run.bat` | 一键启动脚本（模拟器 + Kernel） |
| `charge.bat` | 充满电量快捷脚本 |
| `requirements.txt` | Python 依赖清单（已由 `pyproject.toml` 取代） |
