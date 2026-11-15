"""Static cached-client tests. Every websocket message below is synthetic, not captured."""
import copy
import importlib.util
from pathlib import Path
import unittest

if importlib.util.find_spec('ws_crash_extra'):
    import ws_crash_extra as ws
else:
    ws = None
ROOT = Path(__file__).parent
CACHE = ROOT.parent.parent / 'bgaming-private-chat4/research/legacy'
GIDS = ['BInvestLive', 'DragonsCrash', 'GiftX', 'SpaceXY', 'TopEagle']


def meta(gid='SpaceXY'):
    return ws.metadata(gid, next((CACHE / gid).rglob('bundle.js')).read_text(encoding='utf8'))


def info(gid='SpaceXY', subunits=1000):
    settings = {'currency': 'native-fun', 'currencies': {'native-fun': {'code': 'FUN', 'subunits': subunits}}, 'min_bet': 7, 'max_bet': 700, 'default_bet': 14, 'line_bets': [7, 14, 70]}
    return {'data': [{'state': 'settings', 'changes': settings}, {'state': 'balance', 'changes': {'value': 10007}}, {'state': 'round', 'changes': {'status': 'awaiting'}}]}


def packet(state, changes, request_id=None, action=None):
    p = {'state': state, 'changes': changes}
    if action is not None:
        p['action'] = action
    out = {'data': [p]}
    if request_id is not None:
        out['request_id'] = request_id
    return out


class WebsocketCrashExtra(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ws, 'Source-specific websocket adapter required')

    def context(self, gid='SpaceXY'):
        return ws.game_info(meta(gid), [info(gid)], owned_fresh=True)

    def test_source_metadata_preserves_distinct_counters_and_cashout_shapes(self):
        for gid in GIDS:
            m = meta(gid)
            self.assertEqual(ws.game_info_action(m), {'action': 'game_info'})
            self.assertEqual(m['first_bet_request_id'], 0 if gid == 'BInvestLive' else 2)
        self.assertNotIn('cashout', meta('BInvestLive')['actions'])
        self.assertFalse(meta('GiftX')['cashout_time'])
        self.assertTrue(meta('TopEagle')['cashout_time'])
        with self.assertRaises(ValueError):
            ws.metadata('SpaceXY', 'unreviewed client')

    def test_game_info_uses_currency_lookup_and_never_money_field_name_scaling(self):
        ctx = self.context()
        self.assertEqual((ctx['currency_code'], ctx['subunits'], ctx['balance_native'], ctx['min_bet_native']), ('FUN', 1000, 10007, 7))
        r = ws.prepare(meta(), ctx, 'make_bet', 2, now_ms=1234567)
        self.assertEqual(r, {'action': 'make_bet', 'bet_cents': 7, 'time': 1234567, 'request_id': 2})
        for owned in [False]:
            with self.assertRaises(ValueError):
                ws.game_info(meta(), [info()], owned_fresh=owned)
        changed = info()
        changed['data'][0]['changes']['currencies']['native-fun']['code'] = 'EUR'
        with self.assertRaises(ValueError):
            ws.game_info(meta(), [changed], owned_fresh=True)

    def test_missing_balance_or_existing_owned_bets_blocks_bootstrap(self):
        changed = info()
        changed['data'] = [p for p in changed['data'] if p['state'] != 'balance']
        with self.assertRaises(ValueError):
            ws.game_info(meta(), [changed], owned_fresh=True)
        changed = info()
        changed['data'].append({'state': 'player_bets', 'changes': [{'uuid': 'old-owned', 'bet_cents': 7}]})
        with self.assertRaises(ValueError):
            ws.game_info(meta(), [changed], owned_fresh=True)

    def test_native_auto_targets_are_source_proved_and_envelopes_distinct(self):
        ctx = self.context()
        self.assertEqual(ws.prepare(meta(), ctx, 'make_bet', 2, now_ms=123, auto_native=105)['auto_cashout_set_on'], 105)
        with self.assertRaises(ValueError):
            ws.prepare(meta(), ctx, 'make_bet', 2, now_ms=123, auto_native=1.05)
        ctx['phase'] = 'running'
        ctx['owned_bets'] = {'owned-uuid': {'status': 'accepted', 'stake_native': 7}}
        self.assertEqual(ws.prepare(meta(), ctx, 'cashout', 3, now_ms=456, uuid='owned-uuid'), {'action': 'cashout', 'uuid': 'owned-uuid', 'request_id': 3, 'time': 456})
        gift = self.context('GiftX')
        gift.update(phase='running', coefficient_native=101, owned_bets=ctx['owned_bets'])
        self.assertEqual(ws.prepare(meta('GiftX'), gift, 'cashout', 3, uuid='owned-uuid'), {'action': 'cashout', 'uuid': 'owned-uuid', 'request_id': 3})
        with self.assertRaises(ValueError):
            ws.prepare(meta(), ctx, 'cancel_bet', 4, uuid='owned-uuid')

    def test_binvest_direction_bets_use_zero_first_id_and_have_no_cashout(self):
        m = meta('BInvestLive')
        ctx = self.context('BInvestLive')
        with self.assertRaises(ValueError):
            ws.prepare(m, ctx, 'make_bet', 0, now_ms=123, direction='increase')
        ctx['phase'] = 'waiting'
        self.assertEqual(ws.prepare(m, ctx, 'make_bet', 0, now_ms=123, direction='decrease'), {'action': 'make_bet', 'request_id': 0, 'bet_cents': 7, 'time': 123, 'bet_type': 'decrease'})
        with self.assertRaises(ValueError):
            ws.prepare(m, ctx, 'cashout', 1, uuid='anything')

    def test_actioncable_controls_and_channel_matching(self):
        self.assertEqual(ws.decode_frame(meta(), {'type': 'ping', 'message': 42})['kind'], 'control')
        frame = {'identifier': '{"channel":"CrashGames::GameChannel"}', 'message': info()}
        self.assertEqual(ws.decode_frame(meta(), frame)['message']['data'][0]['state'], 'settings')
        frame['identifier'] = '{"channel":"Other"}'
        with self.assertRaises(ValueError):
            ws.decode_frame(meta(), frame)

    def test_acceptance_requires_request_id_and_uuid_not_amount_matching(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1))
        accepted = {'uuid': 'own-1', 'bet_cents': 7, 'currency': 'native-fun', 'auto_cashout_set_on': None}
        with self.assertRaises(ValueError):
            ledger.ingest(packet('player_bets', accepted, request_id=999))
        ledger.ingest(packet('player_bets', accepted, request_id=2))
        self.assertEqual(ledger.context()['owned_bets']['own-1']['status'], 'accepted')
        # Source UI reserves accepted awaiting bets; raw native balance can still be unchanged.
        ledger.ingest(packet('balance', {'value': 10007}))
        self.assertEqual(ledger.reconcile()['status'], 'pending')

    def test_async_cashout_waits_for_terminal_and_new_balance_and_credits_once(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1, auto_native=105))
        accepted = {'uuid': 'own-1', 'bet_cents': 7, 'currency': 'native-fun', 'auto_cashout_set_on': 105}
        ledger.ingest(packet('player_bets', accepted, request_id=2))
        ledger.ingest(packet('round', {'status': 'running'}))
        won = dict(accepted, win_cents=9, cashout_made_on=130)
        ledger.ingest(packet('player_bets', won))
        ledger.ingest(packet('player_bets', won))
        ledger.ingest(packet('balance', {'value': 10009}))
        ledger.ingest(packet('round', {'status': 'finished'}))
        self.assertEqual(ledger.reconcile()['status'], 'pending')
        ledger.ingest(packet('balance', {'value': 10009}))
        check = ledger.reconcile()
        self.assertEqual((check['status'], check['cost_native'], check['payout_native'], check['actual_native']), ('verified', 7, 9, 10009))
        ledger.ingest(packet('balance', {'value': 10010}))
        with self.assertRaises(ValueError):
            ledger.reconcile()

    def test_broadcast_bets_cannot_create_owned_wins_and_unfinished_is_not_loss(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1))
        ledger.ingest(packet('player_bets', {'uuid': 'own-1', 'bet_cents': 7, 'currency': 'native-fun'}, request_id=2))
        ledger.ingest(packet('bets', {'uuid': 'other', 'bet_cents': 700, 'win_cents': 70000, 'currency': 'native-fun'}))
        ledger.ingest(packet('balance', {'value': 10000}))
        self.assertEqual(ledger.reconcile()['status'], 'pending')
        ledger.ingest(packet('round', {'status': 'finished'}))
        ledger.ingest(packet('balance', {'value': 10000}))
        self.assertEqual(ledger.reconcile()['payout_native'], 0)

    def test_cancel_requires_exact_own_uuid_and_new_balance(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1))
        ledger.ingest(packet('player_bets', {'uuid': 'own-1', 'bet_cents': 7, 'currency': 'native-fun'}, request_id=2))
        ledger.register(ws.prepare(m, ledger.context(), 'cancel_bet', 3, uuid='own-1'))
        ledger.ingest(packet('player_bets', 'own-1', request_id=3, action='remove'))
        self.assertEqual(ledger.reconcile()['status'], 'pending')
        ledger.ingest(packet('balance', {'value': 10007}))
        self.assertEqual((ledger.reconcile()['status'], ledger.reconcile()['cost_native']), ('verified', 0))

    def test_rejection_does_not_count_as_accepted_or_reusable_request(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        request = ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1)
        ledger.register(request)
        with self.assertRaises(ValueError):
            ledger.ingest({'error': 354, 'request_id': 2})
        with self.assertRaises(ValueError):
            ledger.register(request)
        self.assertEqual(ledger.reconcile()['status'], 'blocked')

    def test_crash_zero_win_field_is_still_accepted_until_round_finish(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1))
        ledger.ingest(packet('player_bets', {'uuid': 'own', 'bet_cents': 7, 'currency': 'native-fun', 'win_cents': 0}, request_id=2))
        self.assertEqual(ledger.context()['owned_bets']['own']['status'], 'accepted')

    def test_finished_previous_round_cannot_close_new_accepted_bet(self):
        m = meta()
        ledger = ws.NativeLedger(m, self.context())
        ledger.ingest(packet('round', {'status': 'finished'}))
        ledger.ingest(packet('round', {'status': 'awaiting'}))
        ledger.register(ws.prepare(m, ledger.context(), 'make_bet', 2, now_ms=1))
        ledger.ingest(packet('player_bets', {'uuid': 'own', 'bet_cents': 7, 'currency': 'native-fun'}, request_id=2))
        ledger.ingest(packet('balance', {'value': 10000}))
        self.assertEqual(ledger.reconcile()['status'], 'pending')

    def test_finite_plans_preserve_native_minimum_and_do_not_create_unbounded_autoplay(self):
        plans = ws.mode_plan(meta(), self.context())
        self.assertTrue(any(p['name'] == 'manual_cashout' for p in plans))
        self.assertTrue(any(p['name'] == 'cancel' for p in plans))
        self.assertEqual([p['auto_native'] for p in plans if 'auto_native' in p], [105, 110, 115, 120, 140, 150, 200, 300, 500, 1000])
        self.assertTrue(all(p['maximum_rounds'] == 1 for p in plans))
        self.assertEqual([p['direction'] for p in ws.mode_plan(meta('BInvestLive'), self.context('BInvestLive'))], ['increase', 'decrease', 'increase', 'decrease'])


if __name__ == '__main__':
    unittest.main()
