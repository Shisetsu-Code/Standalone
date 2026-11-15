import json
import unittest
from horizon_initialization import initialize


class FakeSocket:
    def __init__(self, packets):
        self.packets = iter(packets); self.sent = []; self.closed = False
    def send(self, data): self.sent.append(json.loads(data))
    def recv(self): return json.dumps(next(self.packets))
    def close(self): self.closed = True


class InitializationTests(unittest.TestCase):
    def test_only_native_appinfo_is_sent_and_wallet_packets_are_ignored(self):
        expected = {'stakeIncrements': [0.1], 'nextAction': 'spin'}
        socket = FakeSocket([{'payload': {'type': 'balanceUpdated'}},
            {'payload': {'type': 'SlotsResult', 'details': {'params': expected}}}])
        params = initialize('wss://showcase.evo-games.com/public/horizon?balanceId=demo-test',
                            'demo_cookie=example', connect=lambda *a, **k: socket)
        self.assertEqual(params, expected)
        self.assertEqual(len(socket.sent), 1)
        self.assertEqual(socket.sent[0]['payload'], {'type': 'AppInfo', 'recipient': 'rng-slots'})
        self.assertTrue(socket.closed)

    def test_rejection_closes_without_a_play_request(self):
        socket = FakeSocket([{'payload': {'type': 'connection.kickout'}}])
        with self.assertRaises(RuntimeError):
            initialize('wss://showcase.evo-games.com/public/horizon?balanceId=demo-test',
                       '', connect=lambda *a, **k: socket)
        self.assertTrue(socket.closed)
        self.assertEqual(len(socket.sent), 1)

    def test_other_hosts_and_non_demo_wallets_are_rejected_before_connecting(self):
        for url in ['wss://example.com/public/horizon?balanceId=demo-test',
                    'wss://showcase.evo-games.com/public/horizon?balanceId=real']:
            with self.assertRaises(ValueError): initialize(url, '', connect=lambda *a, **k: self.fail())
