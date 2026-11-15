import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from analyze import Sanitizer
from test_ws_crash_extra import meta, info

if importlib.util.find_spec('ws_crash_runtime'):
    import ws_crash_runtime as runtime
else:
    runtime = None
PRIVATE = Path(__file__).resolve().parent.parent.parent / 'bgaming-private-chat4'
IDENTIFIER = json.dumps({'channel': 'CrashGames::GameChannel'}, separators=(',', ':'))


def cfg(gid='SpaceXY'):
    return {'identifier': gid, 'server_id': 'demo', 'currency': 'FUN', 'websocket_url': 'wss://demo.bgaming-network.com/cable?token=REDACTED'}


def frames():
    return [{'type': 'welcome'}, {'type': 'ping', 'message': 42}, {'type': 'confirm_subscription', 'identifier': IDENTIFIER}, {'identifier': IDENTIFIER, 'message': info()}]


class Socket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False
        self.timeout = None
    def settimeout(self, value):
        self.timeout = value
    def send(self, value):
        self.sent.append(json.loads(value))
    def recv(self):
        if not self.incoming:
            raise TimeoutError('synthetic read timeout')
        item = self.incoming.pop(0)
        return item if isinstance(item, str) else json.dumps(item)
    def close(self):
        self.closed = True


class CrashRuntime(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, 'Injected WS bootstrap runtime required')
        self.directory = tempfile.TemporaryDirectory(dir=PRIVATE / 'drafts')
        self.addCleanup(self.directory.cleanup)
        self.parent = SimpleNamespace(game={'game_id': 'SpaceXY'}, page='https://demo.bgaming-network.com/game', clean=Sanitizer(), events=[])
        self.socket = Socket(frames())
        self.factory_calls = []
    def create(self, launch=None, incoming=None, hook=None, gid='SpaceXY'):
        self.parent.game['game_id'] = gid
        if incoming is not None:
            self.socket = Socket(incoming)
        def factory(url, **kwargs):
            self.factory_calls.append({'url': url, **kwargs})
            return self.socket
        self.rt = runtime.CrashBootstrap(self.parent, launch or cfg(gid), meta(gid), socket_factory=factory, private_dir=Path(self.directory.name) / 'new-runtime', owned_fresh=True, checkpoint_hook=hook)
        return self.rt

    def test_handshake_initializes_fun_from_received_settings_and_exact_source_actions(self):
        r = self.create()
        context = r.initialize()
        self.assertEqual((context['currency_code'], context['balance_native'], context['min_bet_native']), ('FUN', 10007, 7))
        self.assertEqual(self.socket.sent[0], {'command': 'subscribe', 'identifier': IDENTIFIER})
        self.assertEqual(json.loads(self.socket.sent[1]['data']), {'action': 'game_info'})
        self.assertEqual(r.next_request_id, 2)
        self.assertEqual(self.factory_calls[0]['subprotocols'], ['actioncable-v1-json'])
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertEqual(len(self.factory_calls), 1)

    def test_binvest_game_info_keeps_first_paid_counter_zero(self):
        incoming = frames()
        incoming[-1]['message'] = info('BInvestLive')
        r = self.create(incoming=incoming, gid='BInvestLive')
        r.initialize()
        self.assertEqual(r.next_request_id, 0)
        self.assertEqual(json.loads(self.socket.sent[1]['data']), {'action': 'game_info'})

    def test_launch_identity_fun_and_official_wss_gate_before_factory_or_private_files(self):
        for changes in [{'currency': 'EUR'}, {'server_id': 'real'}, {'identifier': 'GiftX'}, {'websocket_url': 'ws://demo.bgaming-network.com/cable'}, {'websocket_url': 'wss://bgaming-network.com.attacker.invalid/cable'}, {'websocket_url': 'wss://user:pass@demo.bgaming-network.com/cable'}, {'websocket_url': 'wss://demo.bgaming-network.com:444/cable'}]:
            candidate = dict(cfg(), **changes)
            with self.assertRaises(ValueError):
                self.create(launch=candidate)
            self.assertFalse(self.factory_calls)
            self.assertFalse((Path(self.directory.name) / 'new-runtime').exists())

    def test_private_root_cannot_escape_the_owned_private_area(self):
        with self.assertRaises(ValueError):
            runtime.CrashBootstrap(self.parent, cfg(), meta(), socket_factory=lambda *a, **k: self.fail('No connection'), private_dir=Path.cwd() / 'unsafe-public-log', owned_fresh=True)
        self.assertFalse((Path.cwd() / 'unsafe-public-log').exists())

    def test_send_checkpoint_hook_precedes_every_send_and_private_frames_are_preserved(self):
        order = []
        r = self.create(hook=lambda operation: order.append((operation['status'], len(self.socket.sent))))
        r.initialize()
        self.assertEqual([item for item in order if item[0] == 'sending'], [('sending', 0), ('sending', 1)])
        records = [json.loads(line) for line in (r.private_dir / 'frames.jsonl').read_text().splitlines()]
        self.assertEqual(sum(x['direction'] == 'received' for x in records), 4)
        self.assertEqual(sum(x['direction'] == 'sent' for x in records), 2)
        self.assertIn('syntheticCredential123', (r.private_dir / 'launchcfg.json').read_text())

    def test_public_events_never_expose_ws_auth_url_or_query_tokens(self):
        incoming = frames()
        incoming[-1]['message']['data'].append({'state': 'debug', 'changes': {'value': cfg()['websocket_url'], 'other': 'syntheticCredential123'}})
        r = self.create(incoming=incoming)
        r.initialize()
        public = json.dumps(self.parent.events)
        self.assertNotIn('syntheticCredential123', public)
        self.assertNotIn('wss://', public)
        self.assertIn('10007', public)

    def test_nonsecret_url_parameters_do_not_redact_public_game_currency_or_request_counter(self):
        candidate = cfg()
        candidate['websocket_url'] += '&game=SpaceXY&currency=FUN'
        incoming = frames()
        incoming[-1]['message']['request_id'] = 123
        r = self.create(launch=candidate, incoming=incoming)
        r.initialize()
        self.assertTrue(any(e.get('game_id') == 'SpaceXY' for e in self.parent.events))
        received = next(e['response'] for e in self.parent.events if e['kind'] == 'ws_received')
        self.assertEqual(received['request_id'], 123)
        self.assertEqual(type(received['request_id']), int)
        setting = next(p['changes'] for p in received['data'] if p['state'] == 'settings')
        self.assertEqual(setting['currencies']['native-fun']['code'], 'FUN')
        self.assertNotIn('syntheticCredential123', json.dumps(self.parent.events))

    def test_timeout_after_game_info_preserves_uncertain_checkpoint_and_blocks_retry(self):
        r = self.create(incoming=frames()[:3])
        with self.assertRaises(RuntimeError):
            r.initialize()
        checkpoint = json.loads((r.private_dir / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['operation']['status'], 'uncertain')
        self.assertEqual(len(self.socket.sent), 2)
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertEqual(len(self.socket.sent), 2)

    def test_websocket_client_timeout_type_preserves_uncertainty(self):
        class WebSocketTimeoutException(Exception):
            pass
        r = self.create(incoming=frames()[:3])
        original = self.socket.recv
        def receive():
            if not self.socket.incoming:
                raise WebSocketTimeoutException('synthetic websocket-client timeout')
            return original()
        self.socket.recv = receive
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertEqual(json.loads((r.private_dir / 'checkpoint.json').read_text())['operation']['status'], 'uncertain')
        self.assertEqual(len(self.socket.sent), 2)

    def test_subscribe_send_failure_is_uncertain_and_has_no_retry(self):
        r = self.create()
        def broken_send(value):
            raise TimeoutError('synthetic send timeout')
        self.socket.send = broken_send
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertEqual(json.loads((r.private_dir / 'checkpoint.json').read_text())['operation']['status'], 'uncertain')
        self.assertEqual(len(self.factory_calls), 1)

    def test_wrong_channel_confirmation_rejects_without_game_info(self):
        incoming = frames()
        incoming[2]['identifier'] = '{"channel":"Other"}'
        r = self.create(incoming=incoming)
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertEqual(len(self.socket.sent), 1)

    def test_received_nonfun_settings_cannot_become_initialized(self):
        incoming = frames()
        incoming[-1]['message']['data'][0]['changes']['currencies']['native-fun']['code'] = 'EUR'
        r = self.create(incoming=incoming)
        with self.assertRaises(RuntimeError):
            r.initialize()
        self.assertIsNone(r.context)

    def test_paid_modes_refuse_before_any_send_until_received_schema_review(self):
        r = self.create()
        r.initialize()
        before = len(self.socket.sent)
        with self.assertRaises(RuntimeError):
            r.run_mode({'name': 'manual_cashout'})
        self.assertEqual(len(self.socket.sent), before)
        ledger = r.new_ledger()
        self.assertEqual(ledger.context()['balance_native'], 10007)
        r.close()
        self.assertTrue(self.socket.closed)
        self.assertEqual(json.loads((r.private_dir / 'checkpoint.json').read_text())['operation']['status'], 'received_game_info')


if __name__ == '__main__':
    unittest.main()
