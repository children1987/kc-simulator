"""
openTCS REST API Bridge — 独立桥接层
连接 openTCS REST API ↔ KC 模拟器 (SocketIO + Internal API)

不修改任何 KC 模拟器代码。作为独立进程运行。
用法: python opentcs_bridge.py [--port 55200] [--sim-url http://localhost:8080]
"""
import json
import time
import math
import threading
import argparse
from flask import Flask, jsonify, request

app = Flask(__name__)

# Shared state (updated by SocketIO listener)
_state = {
    'battery': 95.0,
    'position': None,       # point name string
    'agv_state': 0,         # 0=IDLE, 1=RUNNING
    'x': 0.0, 'y': 0.0,
    'heading': 0.0,
    'order_id': 0,
    'points': {},           # {name: {x, y, id}}
    'connected': False,
}
_lock = threading.Lock()


def _find_closest_point(x, y):
    """Find the map point closest to (x, y)."""
    with _lock:
        points = dict(_state['points'])
    best, best_name, best_dist = None, None, float('inf')
    for name, p in points.items():
        d = math.hypot(p['x'] - x, p['y'] - y)
        if d < best_dist:
            best_dist = d
            best_name = name
            best = p
    if best and best_dist < 2.0:
        return best_name
    return None


# ── openTCS-compatible REST API ──

@app.route('/v1/vehicles/<name>')
def api_vehicle(name):
    with _lock:
        battery = _state['battery']
        agv_state = _state['agv_state']
        x, y = _state['x'], _state['y']
    point = _find_closest_point(x, y)
    # Map KC state to openTCS procState
    proc_state = {1: 'EXECUTING'}.get(agv_state, 'IDLE')
    return jsonify({
        'name': name,
        'energyLevel': round(battery, 1),
        'currentPosition': point,
        'procState': proc_state,
        'state': agv_state,
        'integrationLevel': 'TO_BE_UTILIZED',
    })


@app.route('/v1/transportOrders', methods=['POST'])
def api_create_order():
    """Forward order to KC simulator via HTTP."""
    import urllib.request as ureq
    data = request.get_json() or {}
    dests = data.get('destinations', [])
    if not dests:
        return jsonify({'error': 'No destinations'}), 400

    order_name = data.get('name', f'order_{int(time.time())}')

    # Send each destination as a separate nav command
    # KC simulator API: POST /api/action doesn't support nav...
    # Instead, we send via the internal mechanism.
    # For now, use KC simulator's HTTP POST to create nav tasks.
    results = []
    for dest in dests:
        loc = dest.get('locationName', '')
        with _lock:
            pts = dict(_state['points'])
        pt = pts.get(loc)
        if pt is None:
            return jsonify({'error': f'Unknown point: {loc}'}), 400

        # Use the KC simulator's direct nav endpoint (if available)
        try:
            body = json.dumps({'operation': 0, 'point_id': pt['id']}).encode()
            req = ureq.Request(
                'http://localhost:8080/api/nav_control',
                data=body,
                headers={'Content-Type': 'application/json'}
            )
            ureq.urlopen(req, timeout=5)
            results.append({'locationName': loc, 'status': 'sent'})
        except Exception as e:
            print(f'[bridge] Nav error for {loc}: {e}')
            results.append({'locationName': loc, 'status': f'error: {e}'})

    return jsonify({'name': order_name, 'state': 'BEING_PROCESSED', 'destinations': results})


# ── SocketIO listener (polls KC simulator REST API) ──

def _poll_simulator(sim_url: str):
    """Poll KC simulator REST API for status and map."""
    import urllib.request as ureq
    global _state
    while True:
        try:
            # Fetch map
            with ureq.urlopen(f'{sim_url}/api/map', timeout=3) as resp:
                map_data = json.loads(resp.read())
                points = {}
                for p in map_data.get('points', []):
                    points[p['name']] = {'id': p['id'], 'x': p['x'], 'y': p['y']}
                with _lock:
                    _state['points'] = points
                    _state['connected'] = True
        except Exception:
            with _lock:
                _state['connected'] = False

        # Fetch vehicle status via SocketIO proxy (use a simple /api/status endpoint if available)
        # The KC simulator doesn't have a REST status endpoint, so we use a workaround:
        # We run inside the same Python env and can import internals if started together.
        # For a standalone bridge, we'd need SocketIO client or a status endpoint.
        # For now, accept that status comes from the poll loop above (map only).
        time.sleep(1.0)


# ── Internal status updater (called from simulator or set manually) ──

def update_status(battery=None, x=None, y=None, agv_state=None):
    """Called from the KC simulator integration to update bridge state."""
    with _lock:
        if battery is not None:
            _state['battery'] = battery
        if x is not None:
            _state['x'] = x
        if y is not None:
            _state['y'] = y
        if agv_state is not None:
            _state['agv_state'] = agv_state


def start_bridge(host: str = '0.0.0.0', port: int = 55200,
                 sim_url: str = 'http://localhost:8080'):
    """Start the bridge server."""
    threading.Thread(target=_poll_simulator, args=(sim_url,), daemon=True).start()
    print(f'[bridge] openTCS REST bridge on http://{host}:{port}')
    print(f'[bridge] KC simulator at {sim_url}')
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='openTCS REST API Bridge for KC Simulator')
    parser.add_argument('--port', type=int, default=55200, help='Bridge REST port (default: 55200)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Bind address')
    parser.add_argument('--sim-url', type=str, default='http://localhost:8080',
                        help='KC Simulator URL')
    args = parser.parse_args()
    start_bridge(args.host, args.port, args.sim_url)
