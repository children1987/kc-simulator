"""
UDP server — listens on nav port (17804) and qr port (17800),
routes requests to virtual AGVs, and sends back protocol-compliant responses.
"""
import socket
import struct
import threading
import time
import json
from pathlib import Path

from protocol import (
    HEADER_SIZE, MAX_FRAME_SIZE,
    MSG_TYPE_REQUEST, MSG_TYPE_RESPONSE,
    encode_frame, decode_frame,
    encode_cargo_status, encode_subscription_ack,
    decode_subscription_data, decode_immediate_action,
    encode_run_status, encode_nav_status,
    decode_nav_control,
    EXEC, CMD, ACTION,
    RobotStatus, NavigationTask,
)
from agv_engine import VirtualAgv, MapPoint, MapPath


class UdpServer:
    """UDP server simulating one or more Kecong controllers."""

    def __init__(self, nav_port: int = 17804, qr_port: int = 17800,
                 auth_code: bytes = b'KC-SIMULATOR-01',
                 map_config_path: str = 'map_config.json'):
        self.nav_port = nav_port
        self.qr_port = qr_port
        self.auth_code = auth_code[:16].ljust(16, b'\x00')
        self.map_config_path = map_config_path

        self.points: dict[int, MapPoint] = {}
        self.paths: dict[int, MapPath] = {}
        self._load_map()

        self.vehicles: dict[str, VirtualAgv] = {}
        self._create_default_vehicle()

        self.subscriptions: dict[str, dict] = {}

        self.nav_sock: socket.socket | None = None
        self.qr_sock: socket.socket | None = None
        self._running = False
        self._threads: list[threading.Thread] = []

        self.on_packet: callable | None = None
        self.on_status_update: callable | None = None
        self.stats = {'nav_packets': 0, 'qr_packets': 0, 'nav_tasks': 0, 'errors': 0}

    def _load_map(self):
        path = Path(self.map_config_path)
        if path.exists():
            cfg = json.loads(path.read_text(encoding='utf-8'))
            for pt in cfg.get('points', []):
                self.points[pt['id']] = MapPoint(
                    point_id=pt['id'], x=pt['x'], y=pt['y'],
                    name=pt.get('name', str(pt['id'])))
            for p in cfg.get('paths', []):
                self.paths[p['id']] = MapPath(
                    path_id=p['id'],
                    from_point_id=p['from'],
                    to_point_id=p['to'])
        else:
            self._create_default_map()

    def _create_default_map(self):
        for i in range(10):
            self.points[i] = MapPoint(point_id=i, x=i * 3.0, y=0.0, name=str(i))
        for i in range(9):
            self.paths[i] = MapPath(path_id=i, from_point_id=i, to_point_id=i + 1)
        Path(self.map_config_path).write_text(
            json.dumps({
                'points': [{'id': p.point_id, 'x': p.x, 'y': p.y, 'name': p.name}
                           for p in self.points.values()],
                'paths': [{'id': p.path_id, 'from': p.from_point_id, 'to': p.to_point_id}
                          for p in self.paths.values()],
            }, ensure_ascii=False, indent=2), encoding='utf-8')

    def _create_default_vehicle(self):
        sp = next(iter(self.points.values())) if self.points else MapPoint(0, 0, 0)
        self.vehicles['AGV-001'] = VirtualAgv('AGV-001', sp, self.points, self.paths)

    def get_vehicle(self, name: str | None = None) -> VirtualAgv | None:
        if name:
            return self.vehicles.get(name)
        return next(iter(self.vehicles.values()), None)

    def start(self):
        self._running = True
        self.nav_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.nav_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.nav_sock.bind(('0.0.0.0', self.nav_port))
        self.nav_sock.settimeout(0.5)

        self.qr_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.qr_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.qr_sock.bind(('0.0.0.0', self.qr_port))
        self.qr_sock.settimeout(0.5)

        print(f"[UdpServer] Listening on :{self.nav_port} (nav) and :{self.qr_port} (qr)")

        for t in [
            threading.Thread(target=self._nav_loop, daemon=True, name='nav-loop'),
            threading.Thread(target=self._qr_loop, daemon=True, name='qr-loop'),
            threading.Thread(target=self._update_loop, daemon=True, name='update-loop'),
        ]:
            t.start()
            self._threads.append(t)

    def stop(self):
        self._running = False
        for sock in (self.nav_sock, self.qr_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def _nav_loop(self):
        while self._running:
            try:
                data, addr = self.nav_sock.recvfrom(MAX_FRAME_SIZE)
                self.stats['nav_packets'] += 1
                self._handle_packet(data, addr, self.nav_sock, 'nav')
            except socket.timeout:
                continue
            except OSError:
                break

    def _qr_loop(self):
        while self._running:
            try:
                data, addr = self.qr_sock.recvfrom(MAX_FRAME_SIZE)
                self.stats['qr_packets'] += 1
                self._handle_packet(data, addr, self.qr_sock, 'qr')
            except socket.timeout:
                continue
            except OSError:
                break

    def _update_loop(self):
        dt = 1 / 50
        while self._running:
            for v in self.vehicles.values():
                v.update(dt)
            time.sleep(dt)

    def _handle_packet(self, data: bytes, addr: tuple, sock: socket.socket, channel: str):
        frame = decode_frame(data)
        if frame is None:
            self.stats['errors'] += 1
            return
        if not frame['is_request']:
            return

        cmd = frame['command_code']
        cmd_name = _cmd_name(cmd)

        if self.on_packet:
            self.on_packet('recv', addr, cmd_name, data)

        handler = self._get_handler(cmd)
        if handler is None:
            self._send_response(sock, addr, cmd, frame['sequence_number'],
                               EXEC.COMMAND_CODE_ERROR, b'')
            return

        try:
            exec_code, resp_data = handler(frame, addr, channel)
        except Exception:
            import traceback
            traceback.print_exc()
            self.stats['errors'] += 1
            exec_code, resp_data = EXEC.FAILED_UNKNOWN, b''

        resp = self._send_response(sock, addr, cmd, frame['sequence_number'],
                                   exec_code, resp_data)
        if self.on_packet and resp:
            self.on_packet('send', addr, cmd_name + '_RESP', resp)

    def _send_response(self, sock: socket.socket, addr: tuple, cmd: int,
                       seq: int, exec_code: int, data: bytes) -> bytes | None:
        try:
            raw = encode_frame(self.auth_code, cmd, seq, data,
                              msg_type=MSG_TYPE_RESPONSE, execution_code=exec_code)
            sock.sendto(raw, addr)
            return raw
        except OSError:
            return None

    def _get_handler(self, cmd: int):
        return {
            # New "调度" protocol commands
            CMD.NAV_CONTROL: self._h_nav_control,
            CMD.QUERY_RUN_STATUS: self._h_run_status,
            CMD.QUERY_NAV_STATUS: self._h_nav_status,
            CMD.AUTO_MANUAL_SWITCH: self._h_auto_manual_switch,
            # Legacy commands (keep for backward compat)
            CMD.QUERY_ROBOT_STATUS: self._h_query_status,
            CMD.QUERY_CARGO_STATUS: self._h_cargo_status,
            CMD.HYBRID_NAV_TASK: self._h_nav_task,
            CMD.SUBSCRIPTION: self._h_subscription,
            CMD.IMMEDIATE_ACTION: self._h_immediate_action,
            CMD.QUERY_TRAFFIC_REQUEST: self._h_traffic_query,
            CMD.NOTIFY_TRAFFIC_RESULT: self._h_traffic_notify,
            CMD.WRITE_VAR: self._h_write_var,
            CMD.READ_VAR: self._h_read_var,
            CMD.MANUAL_POSITION: self._h_manual_position,
            CMD.CONFIRM_POSITION: self._h_confirm_position,
            CMD.GET_POSITION: self._h_get_position,
        }.get(cmd)

    # ── New "调度" protocol handlers ──

    def _h_nav_control(self, frame, addr, channel):
        """Handle 0x16 NAV_CONTROL (per '调度' protocol)."""
        cmd = decode_nav_control(frame['data'])
        if cmd is None:
            return EXEC.LENGTH_ERROR, b''
        v = self.get_vehicle()
        ok = v.handle_nav_control(cmd)
        if ok:
            self.stats['nav_tasks'] += 1
            return EXEC.SUCCESS, b''
        return EXEC.NAV_STATE_CONFLICT, b''

    def _h_run_status(self, frame, addr, channel):
        """Handle 0x17 QUERY_RUN_STATUS (per '调度' protocol)."""
        v = self.get_vehicle()
        return EXEC.SUCCESS, encode_run_status(v)

    def _h_nav_status(self, frame, addr, channel):
        """Handle 0x1D QUERY_NAV_STATUS (per '调度' protocol)."""
        v = self.get_vehicle()
        return EXEC.SUCCESS, encode_nav_status(v)

    def _h_auto_manual_switch(self, frame, addr, channel):
        """Handle 0x11 AUTO_MANUAL_SWITCH (4-byte payload)."""
        data = frame['data']
        if len(data) >= 1:
            mode = data[0]  # 0=manual, 1=auto
            v = self.get_vehicle()
            if mode == 0:
                v.set_work_mode(1)  # MANUAL
            else:
                v.set_work_mode(3)  # AUTO
        return EXEC.SUCCESS, b''

    # ── Legacy handlers ──

    def _h_query_status(self, frame, addr, channel):
        v = self.get_vehicle()
        self._poll_count = getattr(self, '_poll_count', 0) + 1
        if self._poll_count % 50 == 1:  # 每50次打印一次
            print(f"[POLL] #{self._poll_count} from {addr}, pos=({v.status.position_x:.1f},{v.status.position_y:.1f}) mode={v.status.work_mode} loc={v.status.localization_status}")
        return EXEC.SUCCESS, v.get_status().encode()

    def _h_cargo_status(self, frame, addr, channel):
        v = self.get_vehicle()
        return EXEC.SUCCESS, encode_cargo_status(v.cargo_loaded)

    def _h_nav_task(self, frame, addr, channel):
        task = NavigationTask.decode(frame['data'])
        if task is None or not task.points:
            return EXEC.LENGTH_ERROR, b''
        v = self.get_vehicle()
        ok = v.handle_navigation_task(task)
        if ok:
            self.stats['nav_tasks'] += 1
            return EXEC.SUCCESS, b''
        return EXEC.NAV_STATE_CONFLICT, b''

    def _h_subscription(self, frame, addr, channel):
        sub = decode_subscription_data(frame['data'])
        if sub:
            self.subscriptions[sub['uuid']] = sub
        return EXEC.SUCCESS, encode_subscription_ack([CMD.QUERY_ROBOT_STATUS, CMD.QUERY_CARGO_STATUS])

    def _h_immediate_action(self, frame, addr, channel):
        act = decode_immediate_action(frame['data'])
        if act is None:
            return EXEC.LENGTH_ERROR, b''
        v = self.get_vehicle()
        ok = v.handle_immediate_action(act['action_type'], act['concurrency_mode'],
                                        act['action_id'], act['params'])
        return (EXEC.SUCCESS if ok else EXEC.FAILED_UNKNOWN, b'')

    def _h_traffic_query(self, frame, addr, channel):
        buf = bytearray()
        buf.extend(struct.pack('<H', 0))
        buf.extend(b'\x00' * 14)
        return EXEC.SUCCESS, bytes(buf)

    def _h_traffic_notify(self, frame, addr, channel):
        return EXEC.SUCCESS, b''

    def _h_write_var(self, frame, addr, channel):
        data = frame['data']
        if len(data) >= 17:
            v = self.get_vehicle()
            name_bytes = data[:16].rstrip(b'\x00')
            var_name = name_bytes.decode('ascii', errors='replace')
            value = data[16:20] if len(data) >= 20 else data[16:]
            if var_name == 'NaviControl' and len(value) >= 1:
                v.set_work_mode(value[0])
        return EXEC.SUCCESS, b''

    def _h_read_var(self, frame, addr, channel):
        return EXEC.SUCCESS, b'\x00' * 4

    def _h_read_multi_var(self, frame, addr, channel):
        return EXEC.SUCCESS, b'\x00' * 8

    def _h_write_multi_var(self, frame, addr, channel):
        return EXEC.SUCCESS, b''

    def _h_manual_position(self, frame, addr, channel):
        """Handle 0x14 manual position. Supports DOUBLE (24B, real protocol) or FLOAT (12B, legacy)."""
        v = self.get_vehicle()
        data = frame['data']
        if len(data) >= 24:
            # DOUBLE format (real "调度" protocol)
            x, y, heading = struct.unpack('<ddd', data[:24])
            return EXEC.SUCCESS, v.handle_manual_position(x, y, heading)
        elif len(data) >= 12:
            # FLOAT format (legacy)
            x, y, heading = struct.unpack('<fff', data[:12])
            return EXEC.SUCCESS, v.handle_manual_position(x, y, heading)
        else:
            return EXEC.SUCCESS, v.handle_manual_position()

    def _h_confirm_position(self, frame, addr, channel):
        v = self.get_vehicle()
        v.handle_confirm_position()
        return EXEC.SUCCESS, b''

    def _h_get_position(self, frame, addr, channel):
        v = self.get_vehicle()
        return EXEC.SUCCESS, v.handle_manual_position()


def _cmd_name(cmd: int) -> str:
    names = {
        0x00: 'WRITE_VAR', 0x01: 'READ_VAR', 0x02: 'READ_MULTI_VAR',
        0x03: 'WRITE_MULTI_VAR', 0x11: 'AUTO_MANUAL_SWITCH',
        0x14: 'MANUAL_POSITION', 0x15: 'GET_POSITION',
        0x16: 'NAV_CONTROL', 0x17: 'QUERY_RUN_STATUS',
        0x1D: 'QUERY_NAV_STATUS', 0x1F: 'CONFIRM_POSITION',
        0x70: 'QUERY_TRAFFIC', 0x71: 'NOTIFY_TRAFFIC',
        0xAE: 'HYBRID_NAV', 0xAF: 'QUERY_STATUS',
        0xB0: 'CARGO_STATUS', 0xB1: 'SUBSCRIPTION',
        0xB2: 'IMMEDIATE_ACTION', 0xB7: 'SET_CAPABILITY',
        0xE0: 'MAG_TASK', 0xE1: 'MAG_CONTROL',
        0xE2: 'MAG_STATUS', 0xE3: 'MAG_RELOCALIZE',
        0xF0: 'QR_CONTROL', 0xF1: 'QR_NAV',
        0xF2: 'QR_STATUS', 0xF5: 'QR_LONG_PATH',
        0xF6: 'QR_LONG_ACTION', 0xF7: 'QR_SPLICE_ACTION',
        0xF8: 'QR_SEGMENT_STATUS', 0xB9: 'NEARBY_VEHICLE',
    }
    return names.get(cmd, f'0x{cmd:02X}')
