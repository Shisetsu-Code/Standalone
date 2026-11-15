"""Read-only native AppInfo initialization; never sends play or continue."""
import json
import time
import uuid
from urllib.parse import urlsplit, parse_qs
import websocket


def initialize(url, cookies, *, connect=None, record=None):
    target = urlsplit(url); query = parse_qs(target.query)
    if (target.scheme != 'wss' or target.hostname != 'showcase.evo-games.com'
            or target.path != '/public/horizon' or not query.get('balanceId', [''])[0].startswith('demo-')):
        raise ValueError('Only an observed public Horizon demo socket is supported')
    socket = (connect or websocket.create_connection)(url, cookie=cookies,
        origin='https://showcase.evo-games.com', http_proxy_host='127.0.0.1',
        http_proxy_port=8793, proxy_type='http', timeout=15)
    try:
        message = json.dumps({'id': str(uuid.uuid4()), 'recipient': 'horizon',
                              'payload': {'type': 'AppInfo', 'recipient': 'rng-slots'}})
        if record: record('sent', message)
        socket.send(message); deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            message = socket.recv()
            if not message: raise RuntimeError('Read-only initialization socket closed')
            if record: record('received', message)
            packet = json.loads(message); body = packet.get('payload', packet)
            if body.get('type') in ['connection.kickout', 'error', 'Error', 'SlotsError']:
                raise RuntimeError('Read-only initialization rejected')
            params = body.get('details', {}).get('params', {})
            if body.get('type') == 'SlotsResult' and params.get('stakeIncrements') and params.get('nextAction'):
                return params
        raise TimeoutError('No read-only initialization received')
    finally:
        socket.close()
