#!/usr/bin/env python3
"""
KC Controller Simulator — 科聪 MRC/FRC 控制器软件模拟器
用于在不连接硬件设备的情况下验证 openTCS 上位机软件。

使用方法:
  python main.py                          # 启动模拟器 + Web 仪表板
  python main.py --nav-port 17804 --qr-port 17800 --dashboard-port 8080
  python main.py --map my_map.json        # 使用自定义地图
  python main.py --auth-code MY_AUTH_CODE # 设置协议授权码
"""
import argparse
import sys
import signal
import threading
import time
from pathlib import Path

from udp_server import UdpServer
from dashboard import set_server, add_log, start_dashboard


def main():
    parser = argparse.ArgumentParser(
        description='KC Controller Simulator — 科聪控制器软件模拟器')
    parser.add_argument('--nav-port', type=int, default=17804,
                       help='导航端口 (默认: 17804)')
    parser.add_argument('--qr-port', type=int, default=17800,
                       help='QR/变量操作端口 (默认: 17800)')
    parser.add_argument('--dashboard-port', type=int, default=8080,
                       help='Web 仪表板端口 (默认: 8080)')
    parser.add_argument('--dashboard-host', type=str, default='0.0.0.0',
                       help='仪表板绑定地址 (默认: 0.0.0.0)')
    parser.add_argument('--map', type=str, default='map_config.json',
                       help='地图配置文件路径 (默认: map_config.json)')
    parser.add_argument('--auth-code', type=str, default=None,
                       help='UDP 协议授权码（默认使用科聪标准认证码）')
    parser.add_argument('--max-speed', type=float, default=10.0,
                       help='AGV 最大速度 m/s (默认: 10.0)')
    parser.add_argument('--battery-drain', type=float, default=0.01,
                       help='每到达一个点消耗的电量比例 (默认: 0.01, 设为 0 则完全不耗电)')
    args = parser.parse_args()

    # Resolve map path relative to this script
    map_path = Path(args.map)
    if not map_path.is_absolute():
        script_dir = Path(__file__).resolve().parent
        map_path = script_dir / args.map
        if not map_path.exists():
            map_path = Path.cwd() / args.map

    print("=" * 60)
    print("  KC Controller Simulator V1.0")
    print("  科聪 MRC/FRC 控制器 UDP 协议模拟器")
    print("=" * 60)
    print(f"  导航端口:     {args.nav_port}")
    print(f"  QR/变量端口:  {args.qr_port}")
    auth_label = args.auth_code or "(default binary)"
    print(f"  授权码:       {auth_label}")
    print(f"  地图文件:     {map_path}")
    print(f"  AGV 速度:     {args.max_speed} m/s")
    drain_label = "0 (不耗电)" if args.battery_drain == 0 else f"{args.battery_drain:.0%}"
    print(f"  每步耗电:     {drain_label}")
    print(f"  Web 仪表板:   http://localhost:{args.dashboard_port}")
    print("=" * 60)

    if not map_path.exists():
        print(f"[WARN] 地图文件不存在: {map_path}，将使用默认直线地图")

    # 不指定 --auth-code 则用 UdpServer 默认值（科聪标准二进制认证码）
    server_kwargs = dict(
        nav_port=args.nav_port,
        qr_port=args.qr_port,
        map_config_path=str(map_path),
        battery_drain_per_step=args.battery_drain,
    )
    if args.auth_code is not None:
        server_kwargs['auth_code'] = args.auth_code.encode('ascii', errors='replace')
    server = UdpServer(**server_kwargs)

    for v in server.vehicles.values():
        v.max_speed = args.max_speed

    set_server(server)
    server.on_packet = add_log
    server.start()
    print("[OK] UDP 服务器已启动，等待 openTCS 连接...")

    stop_event = threading.Event()

    def _sig_handler(signum, frame):
        print("\n[INFO] 收到退出信号，正在关闭...")
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    dash_thread = threading.Thread(
        target=start_dashboard,
        args=(args.dashboard_host, args.dashboard_port),
        daemon=True,
        name='dashboard'
    )
    dash_thread.start()
    print(f"[OK] Web 仪表板已启动: http://localhost:{args.dashboard_port}")

    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass

    print("[INFO] 正在关闭模拟器...")
    server.stop()
    print("[OK] 模拟器已退出。")


if __name__ == '__main__':
    main()
