"""
Virtual AGV Engine — simulates a Kecong MRC/FRC controller with realistic movement.
"""
import struct
import time
import math
import threading
from dataclasses import dataclass

from protocol import (
    RobotStatus, NavigationTask, TaskPoint, TaskAction,
    AGV_STATE, WORK_MODE, ACTION,
    NAV_MODE_PATH_SPLICE, NAV_MODE_FREE,
)


@dataclass
class MapPoint:
    point_id: int
    x: float
    y: float
    name: str = ''


@dataclass
class MapPath:
    path_id: int
    from_point_id: int
    to_point_id: int


class VirtualAgv:
    """A single virtual AGV vehicle with state machine and movement simulation."""

    def __init__(self, name: str, start_point: MapPoint, points: dict, paths: dict,
                 max_speed: float = 1.0, max_angular_speed: float = 1.57):
        self.name = name
        self.points = points
        self.paths = paths
        self.max_speed = max_speed
        self.max_angular_speed = max_angular_speed

        self.status = RobotStatus()
        self.status.position_x = start_point.x
        self.status.position_y = start_point.y
        self.status.work_mode = WORK_MODE.AUTO
        self.status.agv_state = AGV_STATE.IDLE
        self.status.localization_status = 3
        self.status.confidence = 100
        self.status.capability_set = 1
        self.status.battery_percent = 0.92
        self.status.battery_voltage = 48.0

        self.current_task: NavigationTask | None = None
        self.current_point_index = 0
        self.last_passed_point_id = start_point.point_id
        self.last_passed_path_id = 0
        self.task_paused = False
        self._task_lock = threading.Lock()

        self._move_start_time = 0.0
        self._move_start_x = 0.0
        self._move_start_y = 0.0
        self._move_duration = 0.0
        self._move_target_x = 0.0
        self._move_target_y = 0.0
        self._move_active = False

        self.cargo_loaded = False
        self.charge_status = 0
        self.error_events: list[tuple[int, int]] = []
        self.action_statuses: list[tuple[int, int]] = []

        # Nav state (per "调度" protocol 0x17/0x1D)
        self.nav_state = 0          # 0=NONE,1=WAIT,2=GOING,3=PAUSE,4=DONE,5=FAIL
        self.current_target_pt = 0
        self.nav_passed_points: list[int] = []
        self.nav_remaining_points: list[int] = []
        self.map_version = 1
        self.map_count = 1
        self.map_name = 'kc-sim-map'
        self.total_distance = 0.0
        self.run_time_ms = 0.0
        self.total_run_time_ms = 0.0

        # Fork/Lift variables
        self.vars: dict[str, int] = {
            'Screen.ForkUp': 0, 'Screen.ForkDown': 0,
            'Button.TopLimit': 0, 'Button.DownLimit': 0,
        }
        self._lift_start_time = 0.0
        self._lift_active = False

    def update(self, dt: float):
        # Transition localization state: 2(locating) → 3(done) after delay
        if self.status.localization_status == 2:
            self.status.localization_status = 3
            self.status.confidence = 100

        # Lift simulation: after LiftUp/Down triggered, set limit after 0.5s
        if self._lift_active:
            import time as _time
            if _time.monotonic() - self._lift_start_time > 0.5:
                if self.vars['Screen.ForkUp']:
                    self.vars['Button.TopLimit'] = 1
                    self.vars['Screen.ForkUp'] = 0
                elif self.vars['Screen.ForkDown']:
                    self.vars['Button.DownLimit'] = 1
                    self.vars['Screen.ForkDown'] = 0
                self._lift_active = False

        if not self._move_active:
            return
        elapsed = time.monotonic() - self._move_start_time
        if elapsed >= self._move_duration:
            self.status.position_x = self._move_target_x
            self.status.position_y = self._move_target_y
            self.status.velocity_x = 0.0
            self.status.velocity_y = 0.0
            self._move_active = False
            self._on_arrive()
        else:
            t = elapsed / self._move_duration if self._move_duration > 0 else 1.0
            t_smooth = t * t * (3 - 2 * t)
            self.status.position_x = self._move_start_x + (self._move_target_x - self._move_start_x) * t_smooth
            self.status.position_y = self._move_start_y + (self._move_target_y - self._move_start_y) * t_smooth
            if self._move_duration > 0:
                dx = self._move_target_x - self._move_start_x
                dy = self._move_target_y - self._move_start_y
                dist = math.hypot(dx, dy)
                speed = dist / self._move_duration
                if dist > 0.001:
                    self.status.velocity_x = speed * dx / dist
                    self.status.velocity_y = speed * dy / dist
                self.status.heading_angle = math.atan2(dy, dx)

    def _on_arrive(self):
        if self.current_task is None:
            return
        points = self.current_task.points
        pt = points[self.current_point_index] if self.current_point_index < len(points) else None
        if pt:
            target = self.points.get(pt.point_id)
            if target:
                self.last_passed_point_id = pt.point_id
                self.status.last_passed_point_id = pt.point_id
            for action in pt.actions:
                self._execute_action(action)
            self.current_point_index += 1

        if self.current_point_index >= len(points):
            self._finish_task()
        else:
            self._start_next_segment()

    def _start_next_segment(self):
        if self.current_task is None or self.task_paused:
            return
        points = self.current_task.points
        if self.current_point_index >= len(points):
            self._finish_task()
            return
        pt = points[self.current_point_index]
        target = self.points.get(pt.point_id)
        if target is None:
            self.current_point_index += 1
            self._start_next_segment()
            return
        self._begin_move_to(target.x, target.y)

    def _begin_move_to(self, x: float, y: float):
        self._move_start_time = time.monotonic()
        self._move_start_x = self.status.position_x
        self._move_start_y = self.status.position_y
        self._move_target_x = x
        self._move_target_y = y
        dx = x - self._move_start_x
        dy = y - self._move_start_y
        dist = math.hypot(dx, dy)
        if dist < 0.001:
            self._move_duration = 2.0
        else:
            self._move_duration = max(dist / self.max_speed, 2.0)
        self._move_active = True
        self.status.agv_state = AGV_STATE.RUNNING

    def _execute_action(self, action: TaskAction):
        aid = action.action_id
        atype = action.action_type
        self.action_statuses.append((aid, 2))
        if atype == ACTION.PALLET_LIFT or atype == ACTION.FORK_LIFT:
            if action.params and len(action.params) > 0:
                if action.params[0] == 1:
                    self.cargo_loaded = True
                elif action.params[0] == 2:
                    self.cargo_loaded = False
        self.action_statuses[-1] = (aid, 3)

    def handle_navigation_task(self, task: NavigationTask) -> bool:
        with self._task_lock:
            if not task.points:
                return False
            self._cancel_current_task()
            self.current_task = task
            self.current_point_index = 0
            self.status.order_id = task.order_id
            self.status.task_key = task.task_key
            self.task_paused = False
            self._start_next_segment()
            return True

    def handle_immediate_action(self, action_type: int, concurrency: int,
                                 action_id: int, params: bytes) -> bool:
        with self._task_lock:
            if action_type == ACTION.PAUSE:
                self.task_paused = True
                self._move_active = False
                self.status.agv_state = AGV_STATE.PAUSED
                self.status.velocity_x = 0.0
                self.status.velocity_y = 0.0
                return True
            elif action_type == ACTION.RESUME:
                self.task_paused = False
                if self.current_task and self.current_point_index < len(self.current_task.points):
                    self._start_next_segment()
                return True
            elif action_type == ACTION.CANCEL:
                self._cancel_current_task()
                return True
            elif action_type in (ACTION.PALLET_LIFT, ACTION.FORK_LIFT):
                if len(params) > 0:
                    self.cargo_loaded = (params[0] == 1)
                return True
            return False

    def _cancel_current_task(self):
        self.current_task = None
        self.current_point_index = 0
        self._move_active = False
        self.task_paused = False
        self.status.order_id = 0
        self.status.task_key = 0
        self.status.agv_state = AGV_STATE.IDLE
        self.status.velocity_x = 0.0
        self.status.velocity_y = 0.0
        self.status.angular_velocity = 0.0
        self.nav_state = 0
        self.current_target_pt = 0
        self.nav_remaining_points = []

    def _finish_task(self):
        self._finish_nav(True)

    def set_work_mode(self, mode: int):
        self.status.work_mode = mode
        if mode == WORK_MODE.MANUAL:
            self._cancel_current_task()
            self.status.agv_state = AGV_STATE.IDLE

    def handle_nav_control(self, cmd: dict) -> bool:
        """Handle 0x16 NAV_CONTROL command (per '调度' protocol).
        Returns True if command accepted."""
        operation = cmd.get('operation', 0)
        point_id = cmd.get('point_id', 0)

        with self._task_lock:
            if operation == 1:  # Cancel
                self._cancel_current_task()
                self.nav_state = 0
                return True
            elif operation == 2:  # Pause
                self.task_paused = True
                self._move_active = False
                self.status.agv_state = AGV_STATE.PAUSED
                self.nav_state = 3
                return True
            elif operation == 3:  # Resume
                self.task_paused = False
                self.nav_state = 2
                if self.current_task and self.current_point_index < len(self.current_task.points):
                    self._start_next_segment()
                return True
            elif operation in (0, 4):  # Start or Create+Pause
                target = self.points.get(point_id)
                if target is None:
                    self.nav_state = 5  # FAIL
                    return False

                self._cancel_current_task()
                self.current_target_pt = point_id
                self.nav_passed_points = [self.last_passed_point_id]
                self.nav_remaining_points = [point_id]

                # Build a simple nav task to the target point
                from protocol import NavigationTask, TaskPoint
                task = NavigationTask(
                    order_id=1, task_key=1,
                    navigation_mode=0,  # PATH_SPLICE
                    points=[TaskPoint(sequence_number=0, point_id=point_id)]
                )
                self.current_task = task
                self.current_point_index = 0
                self.status.order_id = task.order_id
                self.status.task_key = task.task_key
                self.task_paused = (operation == 4)

                if operation == 0:
                    self.nav_state = 2  # GOING
                    self._start_next_segment()
                else:
                    self.nav_state = 3  # PAUSED

                return True
            return False

    def _finish_nav(self, success: bool):
        """Called when navigation completes or fails."""
        with self._task_lock:
            if success:
                self.nav_state = 4  # DONE
                self.last_passed_point_id = self.current_target_pt
                self.status.last_passed_point_id = self.current_target_pt
                self.nav_passed_points.append(self.current_target_pt)
            else:
                self.nav_state = 5  # FAIL
            self.status.order_id = 0
            self.status.task_key = 0
            self.status.agv_state = AGV_STATE.IDLE
            self.current_task = None
            self._move_active = False
            self.current_target_pt = 0
            self.nav_remaining_points = []

    def handle_manual_position(self, x: float = None, y: float = None, heading: float = 0.0):
        """Handle 0x14 manual positioning. If coords provided (DOUBLE format from real protocol),
        update vehicle position and start localization. Returns current position."""
        if x is not None and y is not None:
            self.status.position_x = x
            self.status.position_y = y
            if heading != 0.0:
                self.status.heading_angle = heading
            # Simulate localization: LS=2 (locating) -> LS=3 (done)
            self.status.localization_status = 2
            self.status.confidence = 95
            # Will transition to 3 after a brief delay (handled in update loop)
        return struct.pack('<ddd', self.status.position_x,
                          self.status.position_y, self.status.heading_angle)

    def handle_confirm_position(self) -> bool:
        """Handle 0x1F confirm position."""
        self.status.localization_status = 3
        self.status.confidence = 100
        return True

    def inject_error(self, event_code: int, level: int = 2):
        self.error_events.append((event_code, level))
        if level == 2:
            self.status.agv_state = AGV_STATE.NAV_FAILED

    def clear_errors(self):
        self.error_events.clear()
        if self.status.agv_state == AGV_STATE.NAV_FAILED:
            self.status.agv_state = AGV_STATE.IDLE

    def get_status(self) -> RobotStatus:
        s = self.status
        s.abnormal_events = list(self.error_events)
        s.action_statuses = list(self.action_statuses)
        return s

    @property
    def position(self) -> tuple[float, float]:
        return (self.status.position_x, self.status.position_y)
