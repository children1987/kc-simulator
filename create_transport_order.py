#!/usr/bin/env python3
"""
自动创建运输单脚本 — 通过 openTCS REST API 创建运输单并触发模拟
"""
import requests
import json
import time
import sys

OPENTCS_API = "http://localhost:55200/v1"

def create_transport_order():
    """创建一个从点0到点3的运输单"""

    # 1. 创建运输单
    order_data = {
        "name": f"auto-order-{int(time.time())}",
        "vehicle": "AGV-001",
        "driveOrders": [
            {
                "destination": {
                    "name": "0"
                },
                "actions": []
            },
            {
                "destination": {
                    "name": "3"
                },
                "actions": [
                    {
                        "name": "LOAD",
                        "type": "PalletLift"
                    }
                ]
            }
        ],
        "endTime": None,
        "dependencies": []
    }

    try:
        resp = requests.post(
            f"{OPENTCS_API}/transportOrders",
            json=order_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        resp.raise_for_status()
        order = resp.json()
        print(f"[OK] 运输单创建成功: {order.get('name', 'unknown')}")
        return order
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 创建运输单失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        return None

def get_vehicle_status():
    """获取车辆状态"""
    try:
        resp = requests.get(
            f"{OPENTCS_API}/vehicles/AGV-001",
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 获取车辆状态失败: {e}")
        return None

def trigger_dispatcher():
    """触发调度器"""
    try:
        resp = requests.post(
            f"{OPENTCS_API}/dispatcher/trigger",
            timeout=10
        )
        resp.raise_for_status()
        print("[OK] 调度器已触发")
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 触发调度器失败: {e}")
        return False

def main():
    print("=" * 60)
    print("  自动创建运输单脚本")
    print("=" * 60)

    # 检查 openTCS 是否可访问
    try:
        resp = requests.get(f"{OPENTCS_API}/vehicles", timeout=5)
        resp.raise_for_status()
        print(f"[OK] openTCS API 可访问")
    except Exception as e:
        print(f"[ERROR] 无法连接到 openTCS API: {e}")
        print("  请确保 openTCS Kernel 已启动")
        sys.exit(1)

    # 获取当前车辆状态
    print("\n[INFO] 获取车辆状态...")
    status = get_vehicle_status()
    if status:
        print(f"  车辆: {status.get('name', 'unknown')}")

    # 创建运输单
    print("\n[INFO] 创建运输单...")
    order = create_transport_order()

    if order:
        # 触发调度器
        print("\n[INFO] 触发调度器...")
        trigger_dispatcher()

        print("\n[INFO] 等待运输单执行...")
        print("  (按 Ctrl+C 停止)")

        try:
            while True:
                time.sleep(2)
                status = get_vehicle_status()
                if status:
                    # 尝试获取更多信息
                    print(f"  车辆状态已更新")
        except KeyboardInterrupt:
            print("\n[INFO] 用户中断")

if __name__ == "__main__":
    main()
