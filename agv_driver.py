#!/usr/bin/env python3
"""
直接通过 UDP 协议驱动 AGV 模拟器 — 模拟 openTCS 发送导航任务
包含自动模式初始化序列
"""
import socket
import struct
import time
import sys

HEADER_SIZE = 0x1C
PROTOCOL_VERSION = 0x01
SERVICE_CODE = 0x10
MSG_TYPE_REQUEST = 0x00
MSG_TYPE_RESPONSE = 0x01

CMD_WRITE_VAR = 0x00
CMD_MANUAL_POSITION = 0x14
CMD_CONFIRM_POSITION = 0x1F
CMD_NAV_CONTROL = 0x16
CMD_HYBRID_NAV_TASK = 0xAE
CMD_QUERY_ROBOT_STATUS = 0xAF

EXEC_SUCCESS = 0x00

NAV_MODE_PATH_SPLICE = 0

MAP_POINTS = {
    0: (0, 0),    1: (3, 0),    2: (6, 0),    3: (9, 3),
    4: (9, -3),   5: (12, 3),   6: (12, -3),  7: (15, 3),
    8: (15, -3),  9: (18, 0),
}

NAV_PORT = 17804
AUTH_CODE = b'\xed\x01\xe9\xd2\xb8\xa2\x6b\x4c\x85\x72\x77\xf2\xb2\xcb\x61\xb4'


def encode_frame(auth_code, cmd_code, seq, data, msg_type=MSG_TYPE_REQUEST, exec_code=0):
    ac = auth_code[:16].ljust(16, b'\x00')
    header = struct.pack('<16sBBHBBBxHxx', ac, PROTOCOL_VERSION, msg_type,
                         seq & 0xFFFF, SERVICE_CODE, cmd_code, exec_code, len(data))
    return header + data


def decode_frame(raw):
    if raw is None or len(raw) < HEADER_SIZE:
        return None
    _, _, msg_type, seq, _, cmd_code, exec_code, data_len = \
        struct.unpack_from('<16sBBHBBBxH', raw, 0)
    data = raw[HEADER_SIZE:HEADER_SIZE + data_len]
    return {'cmd': cmd_code, 'exec': exec_code, 'data': data, 'seq': seq}


def send_cmd(sock, addr, cmd_code, seq, data=b'', timeout=2.0):
    frame = encode_frame(AUTH_CODE, cmd_code, seq, data)
    sock.settimeout(timeout)
    sock.sendto(frame, addr)
    try:
        resp, _ = sock.recvfrom(1024)
        return decode_frame(resp)
    except socket.timeout:
        return None


def parse_status(data):
    if len(data) < 84:
        return None
    px, py, heading, last_pt, last_path, pt_seq, conf, loc_status = \
        struct.unpack_from('<fffiiiBB', data, 3)
    work_mode = data[39]
    agv_state = data[40]
    order_id = struct.unpack_from('<i', data, 44)[0]
    battery = struct.unpack_from('<f', data, 64)[0]
    return {
        'position': (px, py), 'heading': heading, 'last_point': last_pt,
        'work_mode': work_mode, 'agv_state': agv_state,
        'order_id': order_id, 'battery': battery,
    }


def write_var(sock, addr, seq, var_name, value):
    var_bytes = var_name.encode('ascii')[:16].ljust(16, b'\x00')
    val_bytes = struct.pack('<i', value) if isinstance(value, int) else value
    payload = var_bytes + val_bytes
    return send_cmd(sock, addr, CMD_WRITE_VAR, seq, payload)


def main():
    if len(sys.argv) < 3:
        print("用法: python agv_driver.py <起点ID> <终点ID>")
        print("例如: python agv_driver.py 0 3")
        sys.exit(1)

    start_id = int(sys.argv[1])
    end_id = int(sys.argv[2])
    print(f"任务: 点 {start_id} -> 点 {end_id}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = ('127.0.0.1', NAV_PORT)
    seq = 0

    # === Step 1: 查询状态 ===
    print("[1/6] 查询 AGV 状态...")
    resp = send_cmd(sock, addr, CMD_QUERY_ROBOT_STATUS, seq)
    seq += 1
    status = parse_status(resp['data']) if resp else None
    if status:
        print(f"  位置: {status['position']}  模式: {status['work_mode']}  状态: {status['agv_state']}")
    else:
        print("  无法获取状态")

    # === Step 2: 切换到手动模式 ===
    print("[2/6] 切换到手动模式 (NaviControl=0)...")
    write_var(sock, addr, seq, 'NaviControl', 0)
    seq += 1
    time.sleep(0.1)

    # === Step 3: 手动定位 ===
    print("[3/6] 执行手动定位...")
    px, py = MAP_POINTS.get(start_id, (0, 0))
    pos_data = struct.pack('<fff', px, py, 0.0)
    resp = send_cmd(sock, addr, CMD_MANUAL_POSITION, seq, pos_data)
    seq += 1
    time.sleep(0.1)

    # === Step 4: 确认位置 ===
    print("[4/6] 确认定位...")
    resp = send_cmd(sock, addr, CMD_CONFIRM_POSITION, seq)
    seq += 1
    time.sleep(0.1)

    # === Step 5: 切换到自动模式 ===
    print("[5/6] 切换到自动模式 (NaviControl=1)...")
    write_var(sock, addr, seq, 'NaviControl', 3)  # 3 = AUTO
    seq += 1
    time.sleep(0.1)

    # 验证状态
    resp = send_cmd(sock, addr, CMD_QUERY_ROBOT_STATUS, seq)
    seq += 1
    status = parse_status(resp['data']) if resp else None
    if status:
        print(f"  当前模式: {status['work_mode']}  状态: {status['agv_state']}")

    # === Step 6: 发送导航任务 ===
    print(f"[6/6] 发送导航任务 (点 {start_id} -> 点 {end_id})...")
    order_id = 1
    point_ids = [start_id, end_id]

    buf = bytearray()
    buf.extend(struct.pack('<iiBBBx', order_id, 1, len(point_ids), 0, NAV_MODE_PATH_SPLICE))
    for i, pt_id in enumerate(point_ids):
        buf.extend(struct.pack('<iifBB6x', i, pt_id, 0.0, 0, 0))

    resp = send_cmd(sock, addr, CMD_HYBRID_NAV_TASK, seq, bytes(buf))
    seq += 1
    if resp and resp['exec'] == EXEC_SUCCESS:
        print("  导航任务已接受!")
    else:
        exec_code = resp['exec'] if resp else -1
        print(f"  导航任务失败! exec_code={exec_code}")
        sock.close()
        sys.exit(1)

    # === 监控运动 ===
    print("\n监控 AGV 运动 (按 Ctrl+C 停止)...\n")
    state_names = {0: 'IDLE', 1: 'RUNNING', 2: 'PAUSED', 3: 'UNINIT',
                   4: 'MANUAL', 6: 'NAV_FAILED'}
    mode_names = {0: 'STANDBY', 1: 'MANUAL', 2: 'SEMI_AUTO', 3: 'AUTO'}

    try:
        while True:
            time.sleep(0.5)
            resp = send_cmd(sock, addr, CMD_QUERY_ROBOT_STATUS, seq)
            seq += 1
            if resp:
                status = parse_status(resp['data'])
                if status:
                    px, py = status['position']
                    st = state_names.get(status['agv_state'], f'??{status["agv_state"]}')
                    md = mode_names.get(status['work_mode'], f'??{status["work_mode"]}')
                    print(f"  ({px:6.1f}, {py:6.1f})  模式={md}  状态={st}  任务ID={status['order_id']}  电量={status['battery']:.0%}")
                    if status['order_id'] == 0 and status['agv_state'] == 0:
                        print("\n[完成] AGV 已到达目标!")
                        break
    except KeyboardInterrupt:
        print("\n[中断]")

    sock.close()


if __name__ == "__main__":
    main()
