"""
Kecong UDP Interface Protocol V2.0 (xRobotProtocol) implementation.
Byte-level compatible with com.kecong.opentcs.protocol.* Java classes.
"""
import struct
from dataclasses import dataclass, field

# ============================================================================
# Frame constants
# ============================================================================
HEADER_SIZE = 0x1C
MAX_DATA_SIZE = 512
MAX_FRAME_SIZE = HEADER_SIZE + MAX_DATA_SIZE
PROTOCOL_VERSION = 0x01
SERVICE_CODE = 0x10
MSG_TYPE_REQUEST = 0x00
MSG_TYPE_RESPONSE = 0x01

# ============================================================================
# Command codes
# ============================================================================
class CMD:
    WRITE_VAR = 0x00
    READ_VAR = 0x01
    READ_MULTI_VAR = 0x02
    WRITE_MULTI_VAR = 0x03
    AUTO_MANUAL_SWITCH = 0x11
    MANUAL_POSITION = 0x14
    GET_POSITION = 0x15
    NAV_CONTROL = 0x16
    QUERY_RUN_STATUS = 0x17
    QUERY_NAV_STATUS = 0x1D
    CONFIRM_POSITION = 0x1F
    QR_TASK_CONTROL = 0xF0
    QR_NAV_TASK = 0xF1
    QR_NAV_STATUS = 0xF2
    QR_LONG_PATH_TASK = 0xF5
    QR_LONG_PATH_ACTION_TASK = 0xF6
    QR_SPLICE_ACTION_TASK = 0xF7
    QR_SEGMENT_STATUS = 0xF8
    MAG_TASK_DISPATCH = 0xE0
    MAG_TASK_CONTROL = 0xE1
    MAG_RUN_STATUS = 0xE2
    MAG_RELOCALIZE = 0xE3
    HYBRID_NAV_TASK = 0xAE
    QUERY_ROBOT_STATUS = 0xAF
    QUERY_CARGO_STATUS = 0xB0
    SUBSCRIPTION = 0xB1
    IMMEDIATE_ACTION = 0xB2
    SET_CAPABILITY = 0xB7
    NEARBY_VEHICLE_INFO = 0xB9
    QUERY_TRAFFIC_REQUEST = 0x70
    NOTIFY_TRAFFIC_RESULT = 0x71

# ============================================================================
# Execution codes
# ============================================================================
class EXEC:
    SUCCESS = 0x00
    FAILED_UNKNOWN = 0x01
    SERVICE_CODE_ERROR = 0x02
    COMMAND_CODE_ERROR = 0x03
    HEADER_ERROR = 0x04
    LENGTH_ERROR = 0x05
    NAV_STATE_CONFLICT = 0x80
    POINT_COUNT_EXCEEDED = 0x83
    SPLICE_OFFSET_MISMATCH = 0x84
    SPLICE_SEQ_MISMATCH = 0x85
    SPLICE_TASK_SEQ_MISMATCH = 0x86
    SPLICE_MAX_EXCEEDED = 0x87
    AUTH_CODE_ERROR = 0xFF

# ============================================================================
# Action types
# ============================================================================
class ACTION:
    PAUSE = 0x01
    RESUME = 0x02
    CANCEL = 0x03
    FORK_LIFT = 0x12
    PALLET_LIFT = 0x16
    CONCURRENT_ALL = 0x00
    CONCURRENT_ACTION_ONLY = 0x01
    CONCURRENT_SINGLE = 0x02

# Navigation modes
NAV_MODE_PATH_SPLICE = 0
NAV_MODE_FREE = 1
NAV_MODE_TARGET_POINT = 2

# AGV states
class AGV_STATE:
    IDLE = 0
    RUNNING = 1
    PAUSED = 2
    UNINITIALIZED = 3
    MANUAL_CONFIRM = 4
    NAV_FAILED = 6

class WORK_MODE:
    STANDBY = 0
    MANUAL = 1
    SEMI_AUTO = 2
    AUTO = 3
    TEACH = 4
    SERVICE = 5
    REPAIR = 6


def encode_frame(auth_code: bytes, command_code: int, seq: int, data: bytes,
                 msg_type: int = MSG_TYPE_REQUEST, execution_code: int = 0) -> bytes:
    data_len = len(data)
    if data_len > MAX_DATA_SIZE:
        raise ValueError(f"Data length {data_len} exceeds max {MAX_DATA_SIZE}")
    ac = auth_code[:16].ljust(16, b'\x00')
    header = struct.pack('<16sBBHBBBxHxx', ac, PROTOCOL_VERSION, msg_type,
                         seq & 0xFFFF, SERVICE_CODE, command_code & 0xFF,
                         execution_code & 0xFF, data_len)
    return header + data


def decode_frame(raw: bytes):
    if raw is None or len(raw) < HEADER_SIZE:
        return None
    auth_code, proto_ver, msg_type, seq, svc_code, cmd_code, exec_code, data_len = \
        struct.unpack_from('<16sBBHBBBxH', raw, 0)
    if data_len > MAX_DATA_SIZE:
        return None
    if len(raw) < HEADER_SIZE + data_len:
        return None
    data = raw[HEADER_SIZE:HEADER_SIZE + data_len]
    return {
        'auth_code': auth_code,
        'protocol_version': proto_ver,
        'message_type': msg_type,
        'sequence_number': seq,
        'service_code': svc_code,
        'command_code': cmd_code,
        'execution_code': exec_code,
        'data': data,
        'is_request': msg_type == MSG_TYPE_REQUEST,
        'is_response': msg_type == MSG_TYPE_RESPONSE,
    }


@dataclass
class RobotStatus:
    # Location
    position_x: float = 0.0
    position_y: float = 0.0
    heading_angle: float = 0.0
    last_passed_point_id: int = 0
    last_passed_path_id: int = 0
    point_sequence_number: int = 0
    confidence: int = 100
    localization_status: int = 3

    # Running
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    angular_velocity: float = 0.0
    work_mode: int = 3
    agv_state: int = 0
    capability_set: int = 1

    # Task
    order_id: int = 0
    task_key: int = 0

    # Battery
    battery_percent: float = 0.85
    battery_voltage: float = 48.0
    battery_current: float = 0.0
    charge_status: int = 0

    # Events
    abnormal_events: list = field(default_factory=list)
    action_statuses: list = field(default_factory=list)

    def encode(self) -> bytes:
        abnormal_size = len(self.abnormal_events)
        action_size = len(self.action_statuses)
        point_size = 0
        path_size = 0
        buf = bytearray()
        buf.extend(struct.pack('<BBH', abnormal_size, action_size, 0))
        # Location (32 bytes)
        buf.extend(struct.pack('<fffiiiBB6x',
            self.position_x, self.position_y, self.heading_angle,
            self.last_passed_point_id, self.last_passed_path_id,
            self.point_sequence_number,
            self.confidence & 0xFF, self.localization_status & 0xFF))
        # Running (20 bytes)
        buf.extend(struct.pack('<fffBBB5x',
            self.velocity_x, self.velocity_y, self.angular_velocity,
            self.work_mode & 0xFF, self.agv_state & 0xFF,
            self.capability_set & 0xFF))
        # Task (12 bytes)
        buf.extend(struct.pack('<iiBB2x', self.order_id, self.task_key,
                               point_size, path_size))
        # Battery (20 bytes)
        buf.extend(struct.pack('<ffffB7x',
            self.battery_percent, self.battery_voltage,
            self.battery_current, float(self.charge_status),
            self.charge_status & 0xFF))
        # Abnormal events (each 12 bytes)
        for event_code, level in self.abnormal_events:
            buf.extend(struct.pack('<HH8x', event_code & 0xFFFF, level & 0xFFFF))
        # Action statuses (each 12 bytes)
        for action_id, status in self.action_statuses:
            buf.extend(struct.pack('<iB7x', action_id, status & 0xFF))
        return bytes(buf)


@dataclass
class TaskAction:
    action_type: int = 0
    concurrency_mode: int = 0
    action_id: int = 0
    params: bytes = field(default_factory=bytes)


@dataclass
class TaskPoint:
    sequence_number: int = 0
    point_id: int = 0
    angle: float = 0.0
    specify_angle: bool = False
    actions: list = field(default_factory=list)


@dataclass
class NavigationTask:
    order_id: int = 0
    task_key: int = 0
    navigation_mode: int = 0
    points: list = field(default_factory=list)
    paths: list = field(default_factory=list)

    @staticmethod
    def decode(data: bytes):
        if len(data) < 12:
            return None
        order_id, task_key, point_size, path_size, nav_mode = \
            struct.unpack_from('<iiBBB', data, 0)
        offset = 12
        task = NavigationTask(
            order_id=order_id, task_key=task_key, navigation_mode=nav_mode)
        for _ in range(point_size):
            pt, offset = _decode_point(data, offset, nav_mode)
            if pt:
                task.points.append(pt)
        return task


def _decode_point(data: bytes, offset: int, nav_mode: int):
    if nav_mode == NAV_MODE_PATH_SPLICE:
        if offset + 20 > len(data):
            return None, offset
        seq, pt_id, angle, specify, action_count = \
            struct.unpack_from('<iifBB6x', data, offset)
        offset += 20
    else:
        if offset + 20 > len(data):
            return None, offset
        seq, angle, specify, action_count, pt_id = \
            struct.unpack_from('<ifBBxxi4x', data, offset)
        offset += 20

    actions = []
    for _ in range(action_count):
        act, offset = _decode_action(data, offset)
        if act:
            actions.append(act)

    return TaskPoint(sequence_number=seq, point_id=pt_id, angle=angle,
                     specify_angle=bool(specify), actions=actions), offset


def _decode_action(data: bytes, offset: int):
    if offset + 12 > len(data):
        return None, offset
    action_type, concurrency, action_id, param_len = \
        struct.unpack_from('<HxBiB', data, offset)
    offset += 12
    params = b''
    if param_len > 0 and offset + param_len <= len(data):
        params = data[offset:offset + param_len]
        offset += param_len
    offset = (offset + 3) & ~3
    return TaskAction(action_type=action_type, concurrency_mode=concurrency,
                      action_id=action_id, params=params), offset


def decode_subscription_data(data: bytes):
    if len(data) < 128:
        return None
    cmds = []
    for i in range(8):
        off = i * 16
        cmd_code = struct.unpack_from('<H', data, off)[0]
        if cmd_code != 0:
            interval = struct.unpack_from('<H', data, off + 2)[0]
            duration = struct.unpack_from('<I', data, off + 4)[0]
            cmds.append({'command': cmd_code, 'interval_ms': interval, 'duration_ms': duration})
    uuid_bytes = data[128:192].rstrip(b'\x00')
    return {'commands': cmds, 'uuid': uuid_bytes.decode('ascii', errors='replace')}


def encode_subscription_ack(commands: list, interval_ms: int = 100, duration_ms: int = 60000) -> bytes:
    buf = bytearray()
    for i in range(8):
        if i < len(commands):
            buf.extend(struct.pack('<HHIB7x', commands[i] & 0xFFFF, interval_ms, duration_ms, 0))
        else:
            buf.extend(b'\x00' * 16)
    buf.extend(b'\x00' * 64)
    return bytes(buf)


def decode_immediate_action(data: bytes):
    if len(data) < 12:
        return None
    action_type, concurrency, action_id, param_len = \
        struct.unpack_from('<HBxiB3x', data, 0)
    params = data[12:12 + param_len] if param_len > 0 else b''
    return {
        'action_type': action_type,
        'concurrency_mode': concurrency,
        'action_id': action_id,
        'params': params,
    }


def encode_cargo_status(loaded: bool) -> bytes:
    return b'\x01' if loaded else b'\x00'


# ============================================================================
# 0x17 QUERY_RUN_STATUS response (per "调度" protocol)
# ============================================================================
def encode_run_status(v) -> bytes:
    """Encode the 0x17 run status response using the real controller format."""
    buf = bytearray()
    # 0x00 DOUBLE 本体温度 (body temp)
    buf.extend(struct.pack('<d', 35.0))
    # 0x08 DOUBLE 位置的X坐标 (m)
    buf.extend(struct.pack('<d', v.status.position_x))
    # 0x10 DOUBLE 位置的Y坐标 (m)
    buf.extend(struct.pack('<d', v.status.position_y))
    # 0x18 DOUBLE 位置的朝向角度 (rad)
    buf.extend(struct.pack('<d', v.status.heading_angle))
    # 0x20 DOUBLE 电池电量 0~1
    buf.extend(struct.pack('<d', v.status.battery_percent))
    # 0x28 U8 是否被阻挡
    buf.extend(struct.pack('<B', 0))
    # 0x29 U8 是否在充电
    buf.extend(struct.pack('<B', v.charge_status))
    # 0x2A U8 运行模式 0=手动 1=自动
    buf.extend(struct.pack('<B', 1 if v.status.work_mode == WORK_MODE.AUTO else 0))
    # 0x2B U8 地图载入状态 0=成功
    buf.extend(struct.pack('<B', 0))
    # 0x2C U32 当前的目标点id
    buf.extend(struct.pack('<I', v.current_target_pt if hasattr(v, 'current_target_pt') else v.last_passed_point_id))
    # 0x30 DOUBLE 前进速度
    buf.extend(struct.pack('<d', v.status.velocity_x))
    # 0x38 DOUBLE 转弯速度
    buf.extend(struct.pack('<d', v.status.angular_velocity))
    # 0x40 DOUBLE 电池电压
    buf.extend(struct.pack('<d', v.status.battery_voltage))
    # 0x48 DOUBLE 电流
    buf.extend(struct.pack('<d', v.status.battery_current))
    # 0x50 U8 当前任务状态: 0=无任务 1=等待 2=前往 3=暂停 4=完成 5=失败 6=退出 7=等待开关门
    nav_state = getattr(v, 'nav_state', 0)
    buf.extend(struct.pack('<B', nav_state))
    # 0x51 U8 保留
    buf.extend(b'\x00')
    # 0x52 U16 地图版本号
    buf.extend(struct.pack('<H', getattr(v, 'map_version', 1)))
    # 0x54 U8[4] 保留
    buf.extend(b'\x00' * 4)
    # 0x58 DOUBLE 累计行驶里程 (m)
    buf.extend(struct.pack('<d', getattr(v, 'total_distance', 0.0)))
    # 0x60 DOUBLE 本次运行时间 (ms)
    buf.extend(struct.pack('<d', getattr(v, 'run_time_ms', 0.0)))
    # 0x68 DOUBLE 累计运行时间 (ms)
    buf.extend(struct.pack('<d', getattr(v, 'total_run_time_ms', 0.0)))
    # 0x70 U8 定位状态: 0=失败 1=成功 2=定位中 3=定位完成
    buf.extend(struct.pack('<B', v.status.localization_status))
    # 0x71 U8[3] 保留
    buf.extend(b'\x00' * 3)
    # 0x74 U32 地图数量
    buf.extend(struct.pack('<I', getattr(v, 'map_count', 1)))
    # 0x78 U8[64] 当前地图名称
    map_name = getattr(v, 'map_name', 'kc-sim-map').encode('ascii')[:64].ljust(64, b'\x00')
    buf.extend(map_name)
    # 0xB8 FLOAT32 置信度 0~1
    buf.extend(struct.pack('<f', v.status.confidence / 100.0))
    # 0xBC U8[4] 保留
    buf.extend(b'\x00' * 4)
    return bytes(buf)


# ============================================================================
# 0x1D QUERY_NAV_STATUS response (per "调度" protocol)
# ============================================================================
def encode_nav_status(v) -> bytes:
    """Encode the 0x1D nav status response."""
    buf = bytearray()
    nav_state = getattr(v, 'nav_state', 0)
    target_pt = getattr(v, 'current_target_pt', 0)
    # 0x00 U8 状态
    buf.extend(struct.pack('<B', nav_state))
    # 0x01 U8[3] 保留
    buf.extend(b'\x00' * 3)
    # 0x04 U16 目标点ID
    buf.extend(struct.pack('<H', target_pt))
    # 0x06 U8[2] 保留
    buf.extend(b'\x00' * 2)
    # 0x08 U16[126] 已经过的路径点ID
    passed = getattr(v, 'nav_passed_points', [])
    for i in range(126):
        if i < len(passed):
            buf.extend(struct.pack('<H', passed[i]))
        else:
            buf.extend(struct.pack('<H', 0))
    # 0x104 U16[126] 未经过的路径点ID
    remaining = getattr(v, 'nav_remaining_points', [])
    for i in range(126):
        if i < len(remaining):
            buf.extend(struct.pack('<H', remaining[i]))
        else:
            buf.extend(struct.pack('<H', 0))
    # pad to match expected length
    return bytes(buf)


# ============================================================================
# 0x16 NAV_CONTROL request decoder (per "调度" protocol, 432-byte payload)
# ============================================================================
def decode_nav_control(data: bytes):
    """Decode 0x16 NAV_CONTROL request."""
    if len(data) < 12:
        return None
    operation = data[0]       # 0=start, 1=cancel, 2=pause, 3=resume, 4=create+pause
    nav_mode = data[1]        # 0=to point, 1=to point on path
    specify_path = data[2]    # 0=no, 1=yes
    traffic = data[3]         # 0=off, 1=on
    # Point ID: ASCII string in bytes 4-11
    point_id_bytes = data[4:12].rstrip(b'\x00')
    point_id_str = point_id_bytes.decode('ascii', errors='replace')
    try:
        point_id = int(point_id_str)
    except ValueError:
        point_id = 0

    result = {
        'operation': operation,
        'nav_mode': nav_mode,
        'specify_path': specify_path,
        'traffic': traffic,
        'point_id': point_id,
        'point_id_str': point_id_str,
    }

    if specify_path and len(data) >= 16:
        result['path_start'] = struct.unpack_from('<H', data, 12)[0]
        result['path_end'] = struct.unpack_from('<H', data, 14)[0]

    return result
