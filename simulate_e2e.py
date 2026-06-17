#!/usr/bin/env python3
"""
端到端模拟脚本 — 模拟完整的 openTCS -> 科聪控制器 -> AGV 运动流程
独立运行，不需要 openTCS，直接通过 UDP 驱动 simulators/kc-simulator
"""
import socket
import struct
import time
import sys

# ============================================================================
# 协议常量
# ============================================================================
HEADER_SIZE = 0x1C
PROTOCOL_VERSION = 0x01
SERVICE_CODE = 0x10
MSG_TYPE_REQUEST = 0x00
MSG_TYPE_RESPONSE = 0x01
EXEC_SUCCESS = 0x00

CMD_WRITE_VAR = 0x00
CMD_MANUAL_POSITION = 0x14
CMD_CONFIRM_POSITION = 0x1F
CMD_HYBRID_NAV_TASK = 0xAE
CMD_QUERY_ROBOT_STATUS = 0xAF

NAV_MODE_PATH_SPLICE = 0
ACTION_PALLET_LIFT = 0x16

NAV_PORT = 17804
AUTH_CODE = b'KC-SIMULATOR-01'

# 地图配置
MAP_POINTS = {
    0: (0, 0, "充电区"),
    1: (3, 0, "通道口A"),
    2: (6, 0, "分叉点"),
    3: (9, 3, "货架A1"),
    4: (9, -3, "货架B1"),
    5: (12, 3, "货架A2"),
    6: (12, -3, "货架B2"),
    7: (15, 3, "加工站C"),
    8: (15, -3, "出货口"),
    9: (18, 0, "终点"),
}

# ============================================================================
# 协议工具函数
# ============================================================================
def encode_frame(cmd_code, seq, data=b''):
    ac = AUTH_CODE[:16].ljust(16, b'\x00')
    header = struct.pack('<16sBBHBBBxHxx', ac, PROTOCOL_VERSION, MSG_TYPE_REQUEST,
                         seq & 0xFFFF, SERVICE_CODE, cmd_code, 0, len(data))
    return header + data


def send_command(sock, addr, cmd_code, seq, data=b'', timeout=2.0):
    sock.settimeout(timeout)
    sock.sendto(encode_frame(cmd_code, seq, data), addr)
    try:
        resp, _ = sock.recvfrom(1024)
        return resp[HEADER_SIZE - 1]  # exec_code
    except socket.timeout:
        return -1


def parse_status(data):
    """解析 RobotStatus — 使用正确的偏移量"""
    if len(data) < 4:
        return None
    # Header: BBH (3 bytes) + 1 byte padding = 4 bytes
    # Location: fff + iii + BB + 6x = 32 bytes
    # Running: fff + BBB + 5x = 20 bytes
    # Task: iiBB + 2x = 12 bytes
    # Battery: ffff + B + 7x = 20 bytes

    offset = 0
    abnormal_size = data[0]
    action_size = data[1]
    offset += 4  # skip header (BBH + 1 pad)

    # Location (32 bytes)
    px, py, heading, last_pt, last_path, pt_seq, conf, loc = \
        struct.unpack_from('<fffiiiBB', data, offset)
    offset += 32

    # Running (20 bytes)
    vx, vy, ang_vel, work_mode, agv_state, cap_set = \
        struct.unpack_from('<fffBBB', data, offset)
    offset += 20

    # Task (12 bytes)
    order_id, task_key, pt_size, path_size = \
        struct.unpack_from('<iiBB', data, offset)

    # Battery (20 bytes)
    batt_offset = offset + 12
    battery = struct.unpack_from('<f', data, batt_offset)[0]

    return {
        'pos': (px, py), 'heading': heading, 'last_point': last_pt,
        'work_mode': work_mode, 'agv_state': agv_state,
        'order_id': order_id, 'battery': battery,
    }


def write_variable(sock, addr, seq, name, value_int):
    var = name.encode('ascii')[:16].ljust(16, b'\x00')
    val = struct.pack('<i', value_int)
    payload = var + val
    assert len(var) == 16, f"Variable name must be 16 bytes, got {len(var)}"
    return send_command(sock, addr, CMD_WRITE_VAR, seq, payload)


def send_nav_task(sock, addr, seq, order_id, point_ids, actions=None):
    buf = bytearray()
    buf.extend(struct.pack('<iiBBBx', order_id, 1, len(point_ids), 0, NAV_MODE_PATH_SPLICE))
    for i, pt_id in enumerate(point_ids):
        action_count = 1 if (actions and i in actions) else 0
        buf.extend(struct.pack('<iifBB6x', i, pt_id, 0.0, 0, action_count))
        if action_count:
            act = actions[i]
            buf.extend(struct.pack('<HxBiB', act['type'], 0, act.get('id', 1), 1))
            buf.extend(bytes([act.get('param', 1)]))
            buf.extend(b'\x00' * 3)
    return send_command(sock, addr, CMD_HYBRID_NAV_TASK, seq, bytes(buf))


def state_name(s):
    return {0: 'IDLE', 1: 'RUNNING', 2: 'PAUSED', 3: 'UNINIT',
            4: 'MANUAL', 6: 'FAILED'}.get(s, f'?{s}')


def mode_name(m):
    return {0: 'STANDBY', 1: 'MANUAL', 2: 'SEMI_AUTO', 3: 'AUTO',
            4: 'TEACH'}.get(m, f'?{m}')


# ============================================================================
# 模拟任务
# ============================================================================
def run_simulation(sock, addr):
    seq = 0

    print("\n" + "=" * 60)
    print("  阶段 1: 查询 AGV 初始状态")
    print("=" * 60)
    resp_data = query_status_raw(sock, addr, seq); seq += 1
    status = parse_status(resp_data) if resp_data else None
    if status:
        print(f"  位置: {status['pos']}  模式: {mode_name(status['work_mode'])}  状态: {state_name(status['agv_state'])}")
    else:
        print("  [WARN] 无法获取状态")

    print("\n" + "=" * 60)
    print("  阶段 2: 自动模式初始化序列")
    print("=" * 60)

    # Step 1: 切换到手动模式
    print("  [1] 切换到手动模式 (NaviControl=1)...")
    write_variable(sock, addr, seq, 'NaviControl', 1); seq += 1
    time.sleep(0.1)

    # Step 2: 手动定位 (从点0开始)
    print("  [2] 手动定位到点 0 (0, 0)...")
    pos_data = struct.pack('<fff', 0.0, 0.0, 0.0)
    send_command(sock, addr, CMD_MANUAL_POSITION, seq, pos_data); seq += 1
    time.sleep(0.1)

    # Step 3: 确认定位
    print("  [3] 确认定位...")
    send_command(sock, addr, CMD_CONFIRM_POSITION, seq); seq += 1
    time.sleep(0.1)

    # Step 4: 切换到自动模式
    print("  [4] 切换到自动模式 (NaviControl=3)...")
    write_variable(sock, addr, seq, 'NaviControl', 3); seq += 1
    time.sleep(0.2)

    # 验证
    resp_data = query_status_raw(sock, addr, seq); seq += 1
    status = parse_status(resp_data) if resp_data else None
    if status:
        print(f"  -> 模式: {mode_name(status['work_mode'])}  状态: {state_name(status['agv_state'])}")

    print("\n" + "=" * 60)
    print("  阶段 3: 创建运输单")
    print("=" * 60)

    # 任务: 从点0 -> 点1 -> 点2 -> 点3 (货架A1) 带取货动作
    # 导航点列表应从当前点的下一个点开始（跳过起始点）
    route = [0, 1, 2, 3]
    route_names = [MAP_POINTS[p][2] for p in route]
    print(f"  任务: {' -> '.join(route_names)}")
    print(f"  动作: 在点 3 执行托盘升起 (LOAD)")

    order_id = 1
    actions = {3: {'type': ACTION_PALLET_LIFT, 'id': 1, 'param': 1}}  # param=1 表示升起
    print(f"  [INFO] 发送导航任务 (order_id={order_id})...")
    ec = send_nav_task(sock, addr, seq, order_id, route, actions); seq += 1
    if ec == EXEC_SUCCESS:
        print("  [OK] 导航任务已接受!")
    else:
        print(f"  [FAIL] 导航任务被拒绝 (exec={ec})")
        return

    # 验证任务已被接受
    resp_data = query_status_raw(sock, addr, seq); seq += 1
    status = parse_status(resp_data) if resp_data else None
    if status:
        print(f"  确认: order_id={status['order_id']}, mode={mode_name(status['work_mode'])}, state={state_name(status['agv_state'])}")

    print("\n" + "=" * 60)
    print("  阶段 4: 监控 AGV 运动")
    print("=" * 60)
    print("  {:>8}  {:>12}  {:>8}  {:>10}  {:>6}".format(
        "时间", "位置", "电量", "状态", "任务ID"))
    print("  " + "-" * 52)

    start_time = time.time()
    last_point = -1
    try:
        while True:
            time.sleep(0.1)
            resp_data = query_status_raw(sock, addr, seq); seq += 1
            status = parse_status(resp_data) if resp_data else None
            if status:
                elapsed = time.time() - start_time
                px, py = status['pos']
                # 检测是否经过了新的点位
                for pt_id, (x, y, name) in MAP_POINTS.items():
                    if abs(px - x) < 1.0 and abs(py - y) < 1.0 and pt_id != last_point:
                        print(f"  {elapsed:6.1f}s  ({px:5.1f},{py:5.1f})  {status['battery']:.0%}  {state_name(status['agv_state']):>10}  {status['order_id']:>6}  <-- 到达: {name}")
                        last_point = pt_id
                        break
                else:
                    if status['agv_state'] == 1 and (px != 0 or py != 0):  # RUNNING 且有位移
                        print(f"  {elapsed:6.1f}s  ({px:5.1f},{py:5.1f})  {status['battery']:.0%}  {state_name(status['agv_state']):>10}  {status['order_id']:>6}")

                if status['order_id'] == 0 and elapsed > 0.5:
                    print(f"\n  [完成] 运输单执行完毕! 总用时 {elapsed:.1f}s")
                    break
    except KeyboardInterrupt:
        print("\n  [中断] 用户停止")

    # 最终状态
    print("\n" + "=" * 60)
    print("  阶段 5: 最终状态")
    print("=" * 60)
    resp_data = query_status_raw(sock, addr, seq)
    status = parse_status(resp_data) if resp_data else None
    if status:
        px, py = status['pos']
        print(f"  最终位置: ({px:.1f}, {py:.1f})")
        print(f"  工作模式: {mode_name(status['work_mode'])}")
        print(f"  AGV 状态: {state_name(status['agv_state'])}")
        print(f"  电量: {status['battery']:.0%}")


def query_status_raw(sock, addr, seq):
    sock.settimeout(2)
    sock.sendto(encode_frame(CMD_QUERY_ROBOT_STATUS, seq), addr)
    try:
        resp, _ = sock.recvfrom(1024)
        return resp[HEADER_SIZE:]
    except socket.timeout:
        return None


# ============================================================================
# 主函数
# ============================================================================
def main():
    print("=" * 60)
    print("  openTCS + 科聪控制器 端到端模拟")
    print("  直接通过 UDP 协议驱动 AGV 模拟器")
    print("=" * 60)

    # 检查模拟器是否运行
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_sock.settimeout(2)
        test_sock.sendto(encode_frame(CMD_QUERY_ROBOT_STATUS, 0), ('127.0.0.1', NAV_PORT))
        resp, _ = test_sock.recvfrom(1024)
        test_sock.close()
        print("[OK] AGV 模拟器已连接 (port %d)" % NAV_PORT)
    except Exception as e:
        print("[ERROR] 无法连接到 AGV 模拟器: %s" % e)
        print("  请先启动 simulators/kc-simulator: python main.py")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = ('127.0.0.1', NAV_PORT)

    try:
        run_simulation(sock, addr)
    except KeyboardInterrupt:
        print("\n[中断] 模拟已停止")
    finally:
        sock.close()

    print("\n[OK] 模拟完成")


if __name__ == "__main__":
    main()
