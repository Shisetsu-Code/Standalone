"""Injected, init-only ActionCable runtime. No default socket factory and no gameplay.

Parent supplies a new owned public demo launchcfg and explicitly instantiates this
class. Source/received action schemas must be reviewed before paid-mode scheduling.
Raw credentials/frames/checkpoints stay only under bgaming-private-chat4. Public
bootstrap events deliberately omit broadcast players and authentication URLs.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, parse_qs
import ws_crash_extra as ws

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT.parent.parent / 'bgaming-private-chat4'


def _official_host(host):
    return isinstance(host, str) and (host == 'bgaming-network.com' or host.endswith('.bgaming-network.com'))


def validate_launch(gid, cfg, *, owned_fresh):
    if owned_fresh is not True or cfg.get('identifier') != gid or cfg.get('currency') != 'FUN' or cfg.get('server_id') != 'demo':
        raise ValueError('New owned public FUN demo identity required')
    url = cfg.get('websocket_url')
    if not isinstance(url, str):
        raise ValueError('Native websocket_url required')
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid official websocket port') from None
    if parsed.scheme != 'wss' or not _official_host(parsed.hostname) or parsed.username or parsed.password or port not in (None, 443) or parsed.fragment:
        raise ValueError('Official secure BGaming websocket URL required')
    return url


def _save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class CrashBootstrap:
    """One fresh connection/bootstrap only; instances cannot reconnect or replay.

    socket_factory(url, timeout=..., subprotocols=[...], origin=...) must return an
    injected websocket-compatible object with send/recv/settimeout/close. The
    parent may wrap websocket.create_connection in a closure that adds its owned
    cookies. No library imports or socket creation happen without initialize().
    checkpoint_hook receives a sanitized summary after the private durable marker,
    before every send. It must not reuse legacy HTTP checkpoint assumptions.
    """
    def __init__(self, parent, cfg, metadata, *, socket_factory, private_dir,
                 owned_fresh, checkpoint_hook=None, timeout_seconds=45,
                 max_frames=2000, clock=time.monotonic):
        gid = parent.game['game_id']
        ws.game_info_action(metadata)
        if metadata['game_id'] != gid:
            raise ValueError('Game-specific metadata mismatch')
        self.url = validate_launch(gid, cfg, owned_fresh=owned_fresh)
        path = Path(private_dir).resolve()
        private_root = PRIVATE.resolve()
        if path == private_root or not path.is_relative_to(private_root):
            raise ValueError('Runtime transcripts must be in a new owned private subdirectory')
        if not callable(socket_factory) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0 or type(max_frames) is not int or max_frames < 1:
            raise ValueError('Injected socket factory and finite receive bounds required')
        page = urlsplit(parent.page)
        if page.scheme != 'https' or not _official_host(page.hostname):
            raise ValueError('Official fresh HTTPS parent page required')
        self.parent = parent
        self.meta = copy.deepcopy(metadata)
        self.cfg = copy.deepcopy(cfg)
        self.factory = socket_factory
        self.private_dir = path
        self.hook = checkpoint_hook
        self.timeout = timeout_seconds
        self.max_frames = max_frames
        self.clock = clock
        self.origin = 'https://' + page.netloc
        self.identifier = json.dumps({'channel': ws.CHANNEL}, separators=(',', ':'))
        self.next_request_id = metadata['first_bet_request_id']
        self.context = None
        self.native_messages = []
        self.socket = None
        self.started = self.closed = False
        self.frame_count = 0
        self.operation = {'status': 'created'}
        self._secrets = {self.url}
        for key, values in parse_qs(urlsplit(self.url).query).items():
            if re.search(r'token|secret|password|cookie|session|auth|key|signature|credential|jwt|access', key, re.I):
                self._secrets.update(v for v in values if v)
        def secrets(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, str) and re.search(r'token|secret|password|cookie|authorization|session', key, re.I) and item:
                        self._secrets.add(item)
                    secrets(item)
            elif isinstance(value, list):
                for item in value:
                    secrets(item)
        secrets(cfg)
        # Refuse existing paths: a new Python object cannot resume an uncertain socket.
        path.mkdir(parents=True, exist_ok=False)
        _save(path / 'launchcfg.json', cfg)
        self._checkpoint({'status': 'created'})

    def _clean(self, value):
        def scrub(item):
            if isinstance(item, str):
                result = re.sub(r'(?:wss?|https?)://[^\s<>"\x27]+', '[REDACTED_URL]', item)
                for secret in sorted(self._secrets, key=len, reverse=True):
                    result = result.replace(secret, '[REDACTED]')
                return result
            if isinstance(item, dict):
                return {key: scrub(v) for key, v in item.items()}
            if isinstance(item, list):
                return [scrub(v) for v in item]
            return item
        cleaner = self.parent.clean.clean if hasattr(self.parent.clean, 'clean') else self.parent.clean
        result = cleaner(scrub(copy.deepcopy(value)))
        # These are local source counters, never player/account/session identifiers.
        def counters(native, public):
            if isinstance(native, dict) and isinstance(public, dict):
                for key, v in native.items():
                    if key == 'request_id' and type(v) is int:
                        public[key] = v
                    elif key in public:
                        counters(v, public[key])
            elif isinstance(native, list) and isinstance(public, list):
                for a, b in zip(native, public):
                    counters(a, b)
        counters(value, result)
        return result

    def _checkpoint(self, operation):
        self.operation = copy.deepcopy(operation)
        _save(self.private_dir / 'checkpoint.json', dict(game_id=self.meta['game_id'],
              source_sha256=self.meta['source_sha256'], operation=operation,
              next_request_id=self.next_request_id, received_frames=self.frame_count,
              context=self.context))
        if self.hook:
            self.hook(self._clean(dict(game_id=self.meta['game_id'], **operation)))

    def _raw(self, direction, raw):
        record = dict(time=datetime.now(timezone.utc).isoformat(), direction=direction, raw=raw)
        with (self.private_dir / 'frames.jsonl').open('a', encoding='utf8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def _event(self, kind, **value):
        event = dict(time=datetime.now(timezone.utc).isoformat(), kind=kind,
                     protocol='bgaming-actioncable', game_id=self.meta['game_id'], **value)
        self.parent.events.append(self._clean(event))

    def _send(self, frame, label, deadline):
        if self.closed or self.clock() >= deadline:
            raise TimeoutError('Finite bootstrap deadline reached')
        text = json.dumps(frame, separators=(',', ':'))
        self._checkpoint(dict(status='sending', action=label,
                              frame_sha256=hashlib.sha256(text.encode()).hexdigest()))
        self._raw('sent', text)
        try:
            self.socket.send(text)
        except Exception:
            self._checkpoint(dict(status='uncertain', action=label, reason='send_failure'))
            raise
        self._event('ws_sent', request=({'action': 'game_info'} if label == 'game_info' else {'action': 'subscribe', 'channel': ws.CHANNEL}))

    def _receive(self, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0 or self.frame_count >= self.max_frames:
            raise TimeoutError('Finite bootstrap receive bound reached')
        self.socket.settimeout(remaining)
        raw = self.socket.recv()
        if isinstance(raw, bytes):
            raw = raw.decode('utf8')
        self._raw('received', raw)
        self.frame_count += 1
        if not isinstance(raw, str) or not raw or len(raw) > 4 * 1024 * 1024:
            raise ValueError('Empty or unsupported websocket frame retained privately')
        decoded = json.loads(raw)
        return ws.decode_frame(self.meta, decoded)

    def _public_game_message(self, message):
        if message.get('error'):
            return {'error': message['error'], 'request_id': message.get('request_id')}
        items = []
        for item in message.get('data', []):
            state, changes = item.get('state'), item.get('changes')
            if state == 'settings' and isinstance(changes, dict):
                selected = changes.get('currency')
                currencies = changes.get('currencies', {})
                currency = currencies.get(str(selected), currencies.get(selected, {}))
                safe = {key: changes[key] for key in ['currency', 'min_bet', 'max_bet', 'default_bet', 'line_bets'] if key in changes}
                safe['currencies'] = {str(selected): {key: currency[key] for key in ['code', 'subunits'] if key in currency}}
            elif state == 'balance' and isinstance(changes, dict):
                safe = {'value': changes.get('value')}
            elif state == 'round' and isinstance(changes, dict):
                safe = {'status': changes.get('status')}
            else:
                continue  # No other players, authentication/debug or opaque source payloads.
            items.append({'state': state, 'changes': safe})
        result = {'data': items}
        if type(message.get('request_id')) is int:
            result['request_id'] = message['request_id']
        return result

    def initialize(self):
        if self.started or self.closed:
            raise RuntimeError('Bootstrap already attempted; uncertain contexts are never retried')
        self.started = True
        deadline = self.clock() + self.timeout
        confirmed = subscribed = False
        seen = set()
        try:
            self._checkpoint({'status': 'connecting'})
            self.socket = self.factory(self.url, timeout=self.timeout,
                                       subprotocols=['actioncable-v1-json'], origin=self.origin)
            while True:
                frame = self._receive(deadline)
                if frame['kind'] == 'control':
                    kind = frame['type']
                    self._event('ws_control', response={'type': kind})
                    if kind in ('disconnect', 'reject_subscription'):
                        raise ValueError('Official websocket subscription refused/disconnected')
                    if kind == 'welcome':
                        if subscribed:
                            raise ValueError('Repeated welcome cannot resubscribe/replay')
                        self._send({'command': 'subscribe', 'identifier': self.identifier}, 'subscribe', deadline)
                        subscribed = True
                    elif kind == 'confirm_subscription':
                        if not subscribed or confirmed:
                            raise ValueError('Unexpected subscription confirmation')
                        confirmed = True
                        self._send({'command': 'message', 'identifier': self.identifier,
                                    'data': json.dumps(ws.game_info_action(self.meta), separators=(',', ':'))}, 'game_info', deadline)
                        self._checkpoint({'status': 'awaiting_game_info'})
                    continue
                if not confirmed:
                    raise ValueError('Game message arrived before owned subscription confirmation')
                message = frame['message']
                self.native_messages.append(copy.deepcopy(message))
                self._event('ws_received', response=self._public_game_message(message))
                if message.get('error'):
                    raise ValueError('Native websocket game_info returned provider error')
                for packet in message['data']:
                    seen.add(packet['state'])
                if {'settings', 'balance', 'round'} <= seen:
                    context = ws.game_info(self.meta, self.native_messages, owned_fresh=True)
                    for previous in self.native_messages:
                        for packet in previous['data']:
                            if packet['state'] == 'waiting' and self.meta['game_id'] == 'BInvestLive':
                                context['phase'] = 'waiting'
                    self.context = context
                    self._checkpoint({'status': 'received_game_info', 'source_validated': True})
                    return copy.deepcopy(context)
        except Exception as error:
            uncertain = (self.operation.get('status') == 'uncertain' or isinstance(error, (TimeoutError, OSError))
                         or type(error).__name__ in ('WebSocketTimeoutException', 'WebSocketConnectionClosedException'))
            self._checkpoint(dict(status='uncertain' if uncertain else 'failed_received',
                                  reason=type(error).__name__, no_retry=True))
            self.close()
            raise RuntimeError('WS bootstrap ' + ('uncertain; no retry' if uncertain else 'stopped; private evidence retained')) from None

    def new_ledger(self):
        if self.context is None or self.closed or self.operation.get('status') != 'received_game_info':
            raise RuntimeError('Source-validated owned game_info required')
        ledger = ws.NativeLedger(self.meta, copy.deepcopy(self.context))
        ledger.next_request_id = self.next_request_id
        return ledger

    def run_mode(self, mode):
        raise RuntimeError('Paid WS scheduling is not enabled; received bootstrap and action-ack schema review is required')

    def close(self):
        if not self.closed:
            self.closed = True
            if self.socket is not None:
                try:
                    self.socket.close()
                except Exception:
                    pass
        # Never overwrite an uncertain marker or received checkpoint during cleanup.
