"""
Flask Web Dashboard — real-time visualization of virtual AGV and communication log.
"""
import json
import threading
import time
from pathlib import Path

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kc-sim-secret'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

_server = None
_logs = []
_max_logs = 200


def set_server(server):
    global _server
    _server = server


def add_log(direction: str, addr: tuple, cmd: str, raw: bytes):
    global _logs
    _logs.append({
        'ts': time.strftime('%H:%M:%S'),
        'dir': direction,
        'addr': f'{addr[0]}:{addr[1]}' if isinstance(addr, tuple) else str(addr),
        'cmd': cmd,
        'raw': raw.hex(' '),
    })
    if len(_logs) > _max_logs:
        del _logs[:len(_logs) - _max_logs]
    socketio.emit('log', _logs[-1])


def _emit_status():
    while True:
        time.sleep(0.2)
        if _server is None or not _server.vehicles:
            continue
        for name, v in _server.vehicles.items():
            s = v.status
            socketio.emit('status', {
                'name': name,
                'x': s.position_x,
                'y': s.position_y,
                'heading': s.heading_angle,
                'vx': s.velocity_x,
                'vy': s.velocity_y,
                'work_mode': s.work_mode,
                'agv_state': s.agv_state,
                'order_id': s.order_id,
                'battery': round(s.battery_percent * 100, 1),
                'cargo': v.cargo_loaded,
                'loc_status': s.localization_status,
                'errors': [{'code': hex(c), 'level': l} for c, l in v.error_events],
                'stats': dict(_server.stats),
            })


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/map')
def api_map():
    if _server is None:
        return jsonify({'points': [], 'paths': []})
    return jsonify({
        'points': [{'id': p.point_id, 'x': p.x, 'y': p.y, 'name': p.name}
                   for p in _server.points.values()],
        'paths': [{'id': p.path_id, 'from': p.from_point_id, 'to': p.to_point_id}
                  for p in _server.paths.values()],
    })


@app.route('/api/logs')
def api_logs():
    return jsonify(_logs)


@app.route('/api/inject_error', methods=['POST'])
def api_inject_error():
    v = _server.get_vehicle()
    if v is None:
        return jsonify({'ok': False, 'msg': 'No vehicle'})
    data = request.get_json() or {}
    code = data.get('code', 0x1001)
    level = data.get('level', 2)
    v.inject_error(code, level)
    return jsonify({'ok': True})


@app.route('/api/clear_errors', methods=['POST'])
def api_clear_errors():
    v = _server.get_vehicle()
    if v is not None:
        v.clear_errors()
    return jsonify({'ok': True})


@app.route('/api/charge', methods=['POST'])
def api_charge():
    """充满电 — 将车辆电量设为 100%"""
    v = _server.get_vehicle()
    if v is None:
        return jsonify({'ok': False, 'msg': 'No vehicle'})
    v.charge_battery()
    return jsonify({'ok': True, 'battery': 100.0})


@app.route('/api/action', methods=['POST'])
def api_action():
    v = _server.get_vehicle()
    if v is None:
        return jsonify({'ok': False, 'msg': 'No vehicle'})
    data = request.get_json() or {}
    action_name = data.get('action', 'pause')
    from protocol import ACTION
    action_map = {
        'pause': (ACTION.PAUSE, b''),
        'resume': (ACTION.RESUME, b''),
        'cancel': (ACTION.CANCEL, b''),
        'load': (ACTION.PALLET_LIFT, b'\x01'),
        'unload': (ACTION.PALLET_LIFT, b'\x02'),
    }
    at, params = action_map.get(action_name, (ACTION.PAUSE, b''))
    import time as _time
    v.handle_immediate_action(at, 0x02, int(_time.time() * 1000) & 0x7FFFFFFF, params)
    return jsonify({'ok': True})


@socketio.on('connect')
def on_connect():
    emit('connected', {'msg': 'OK'})


def start_dashboard(host: str = '0.0.0.0', port: int = 8080):
    threading.Thread(target=_emit_status, daemon=True).start()
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
