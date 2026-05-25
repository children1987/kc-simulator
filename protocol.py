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
