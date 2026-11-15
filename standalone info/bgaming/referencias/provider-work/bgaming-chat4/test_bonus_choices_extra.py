import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parent
PRIVATE = ROOT.parent.parent / 'bgaming-private-chat4'
SPEC = importlib.util.find_spec('bonus_choices_extra')
if SPEC:
    import bonus_choices_extra as adapter
else:
    adapter = None


def source(gid):
    if gid == 'LuckyLadyClover':
        return (PRIVATE / 'research/classic/casino.min.js').read_text(encoding='utf8')
    return next((PRIVATE / 'research/legacy' / gid).rglob('bundle.js')).read_text(encoding='utf8')


def report(gid):
    preferred = {
        'DigDigDigger': 'DigDigDigger.before-dig-choice-recovery.json',
        'WildMoonThieves': 'WildMoonThieves.before-manual-doors.json',
    }
    archive = ROOT / 'live/attempts' / preferred.get(gid, 'unused-reference-name.json')
    candidates = ([archive] if archive.exists() else []) + sorted((ROOT / 'live/attempts').glob(gid + '*.json')) + [ROOT / 'live' / (gid + '.json')]
    captured = None
    for candidate in candidates:
        data = json.loads(candidate.read_text(encoding='utf8'))
        events = data.get('events', [])
        if gid == 'WildMoonThieves' and not any(e.get('response', {}).get('flow', {}).get('state') == 'preselection_game' for e in events):
            continue
        if gid == 'LuckyLadyClover' and (len(events) < 3 or events[1].get('response', {}).get('bets', {}).get('required_for_bonus_game') != 150):
            continue
        if events:
            captured = data
            break
    if captured is None:
        raise AssertionError('Accepted archived bonus fixture missing: ' + gid)
    if gid == 'DigDigDigger':
        # Fixed received initial/min-spin prefix, independent of subsequent parent gameplay.
        captured['events'] = captured['events'][:2]
    return captured


class BonusChoicesExtra(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(adapter, 'Source-specific choice adapter is required')

    def test_digger_semantic_choice_envelope_and_collect(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        current = report('DigDigDigger')['events'][-1]['response']
        for choice in ['s', 'c', 'd', 'h', 'black', 'red']:
            self.assertEqual(adapter.prepare(current, meta, choice), {'command': 'gamble', 'options': {'bet': choice}})
        self.assertEqual(adapter.prepare(current, meta, 'collect'), {'command': 'close'})
        for choice in [10, True, 'spades', 'unknown']:
            with self.assertRaises(ValueError):
                adapter.prepare(current, meta, choice)

    def test_digger_source_native_gamble_ledger_and_no_double_collect(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        before = report('DigDigDigger')['events'][-1]['response']
        # Synthetic source-schema win, deliberately not a received gamble fixture.
        after = copy.deepcopy(before)
        after.update(gamble={'win': True, 'value': '000s'})
        after['balance'] = {'wallet': 99990, 'game': 40}
        after['flow']['command'] = 'gamble'
        after['flow']['last_action_id'] = 'action-2'
        check = adapter.check_event(before, {'request': {'command': 'gamble', 'options': {'bet': 's'}}, 'response': after, 'status': 200}, meta)
        self.assertEqual((check['stake_native'], check['payout_native']), (10, 40))
        self.assertEqual(check['effective_balance_native'], 100030)
        closed = copy.deepcopy(after)
        closed['flow'].update(command='close', state='closed', last_action_id='action-2', available_actions=['init', 'spin'])
        self.assertTrue(adapter.check_event(after, {'request': {'command': 'close'}, 'response': closed, 'status': 200}, meta)['ok'])
        for bad in [dict(after, balance={'wallet': 99991, 'game': 40}), dict(after, gamble={'win': False, 'value': '000s'})]:
            with self.assertRaises(ValueError):
                adapter.check_event(before, {'request': {'command': 'gamble', 'options': {'bet': 's'}}, 'response': bad, 'status': 200}, meta)
        closed['balance']['wallet'] += 40
        with self.assertRaises(ValueError):
            adapter.check_event(after, {'request': {'command': 'close'}, 'response': closed, 'status': 200}, meta)

    def test_digger_closed_loss_zeroes_pending_stake_without_wallet_debit(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        before = report('DigDigDigger')['events'][-1]['response']
        after = copy.deepcopy(before)
        after.update(gamble={'win': False, 'value': '000h'}, balance={'wallet': 99990, 'game': 0})
        after['flow'].update(command='gamble', state='closed', last_action_id='action-2', available_actions=['init', 'spin'])
        checked = adapter.check_event(before, {'request': {'command': 'gamble', 'options': {'bet': 'black'}}, 'response': after, 'status': 200}, meta)
        self.assertEqual(checked['payout_native'], 0)
        self.assertEqual(checked['effective_balance_native'], 99990)

    def test_api2_numeric_win_zero_is_loss_and_received_wallet_jump_stays_failed(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        before = report('DigDigDigger')['events'][1]['response']
        # Received Dig response schema, with synthetic wallet for isolated schema validation.
        after = copy.deepcopy(before)
        after.update(gamble={'history': ['ac'], 'value': ['suit', 's', 'c', 'a'], 'bet': 10, 'win': 0}, balance={'wallet': 99990, 'game': 0})
        after['flow'].update(command='gamble', state='closed', last_action_id='action-received', available_actions=['init', 'spin'])
        event = {'request': {'command': 'gamble', 'options': {'bet': 's'}}, 'response': after, 'status': 200}
        self.assertEqual(adapter.check_event(before, event, meta)['payout_native'], 0)
        after['balance']['wallet'] = 100000
        with self.assertRaisesRegex(ValueError, 'balance/outcome mismatch'):
            adapter.check_event(before, event, meta)
        after['balance']['wallet'] = 99990
        after['gamble']['bet'] = 20
        with self.assertRaises(ValueError):
            adapter.check_event(before, event, meta)

    def test_manual_doors_accept_only_source_indices_and_reject_zero_already_open(self):
        meta = adapter.metadata('WildMoonThieves', source('WildMoonThieves'))
        before = next(e['response'] for e in report('WildMoonThieves')['events'] if e['response'].get('flow', {}).get('state') == 'preselection_game')
        for index in [0, 15]:
            self.assertEqual(adapter.prepare(before, meta, index), {'command': 'play_preselection_game', 'options': {'index': index}})
        for index in [-1, 16, True, '0', 0.0]:
            with self.assertRaises(ValueError):
                adapter.prepare(before, meta, index)
        before = copy.deepcopy(before)
        before.setdefault('features', {})['preselection_game'] = {'doors': [{'index': 0, 'wilds': 2}], 'finished': False}
        with self.assertRaises(ValueError):
            adapter.prepare(before, meta, 0)

    def test_manual_door_result_confirms_choice_history_and_native_wallet(self):
        meta = adapter.metadata('WildMoonThieves', source('WildMoonThieves'))
        before = copy.deepcopy(next(e['response'] for e in report('WildMoonThieves')['events'] if e['response'].get('flow', {}).get('state') == 'preselection_game'))
        after = copy.deepcopy(before)
        after['flow'].update(command='play_preselection_game', last_action_id='action-next')
        after['features']['preselection_game'] = {'doors_auto_open_flag': False, 'doors': [{'index': 0, 'wilds': 2}], 'new_doors': [{'index': 0, 'wilds': 2}], 'finished': False}
        event = {'request': {'command': 'play_preselection_game', 'options': {'index': 0}}, 'response': after, 'status': 200}
        self.assertTrue(adapter.check_event(before, event, meta)['ok'])
        event['response']['balance']['wallet'] += 1
        with self.assertRaises(ValueError):
            adapter.check_event(before, event, meta)

    def test_classic_specific_six_choices_native_stake_result_and_collect(self):
        meta = adapter.metadata('LuckyLadyClover', source('LuckyLadyClover'))
        before = report('LuckyLadyClover')['events'][1]['response']
        self.assertEqual(adapter.prepare(before, meta, 'h'), {'command': 'check_card', 'options': {'bet': 'h'}})
        self.assertEqual(adapter.prepare(before, meta, 'collect'), {'command': 'finish'})
        # Classic source reads result.total; no Aztec-specific bets.bonus_game requirement.
        after = {'balance': 100510, 'game': {'state': 'check_card', 'action': 'check_card', 'bonus_game': {'result': 'win', 'card': '6H'}}, 'bets': {'required_for_bonus_game': 600}, 'result': {'total': 600}, 'available_commands': ['check_card', 'finish', 'init']}
        event = {'request': {'command': 'check_card', 'options': {'bet': 'h'}}, 'response': after, 'status': 200}
        checked = adapter.check_event(before, event, meta)
        self.assertEqual((checked['stake_native'], checked['payout_native'], checked['effective_balance_native']), (150, 600, 100510))
        after['balance'] += 1
        with self.assertRaises(ValueError):
            adapter.check_event(before, event, meta)
        finish = report('LuckyLadyClover')['events'][2]
        self.assertTrue(adapter.check_event(before, finish, meta)['ok'])

    def test_classic_loss_missing_result_is_zero_and_bad_result_not_tolerated(self):
        meta = adapter.metadata('LuckyLadyClover', source('LuckyLadyClover'))
        before = report('LuckyLadyClover')['events'][1]['response']
        after = {'balance': 99910, 'game': {'state': 'closed', 'action': 'check_card', 'bonus_game': {'result': 'lose', 'card': '6H'}}, 'available_commands': ['init', 'spin']}
        event = {'request': {'command': 'check_card', 'options': {'bet': 'black'}}, 'response': after, 'status': 200}
        self.assertEqual(adapter.check_event(before, event, meta)['payout_native'], 0)
        after['result'] = {'total': 1}
        with self.assertRaises(ValueError):
            adapter.check_event(before, event, meta)

    def test_source_mismatch_and_cross_game_metadata_cannot_dispatch(self):
        for gid in ['DigDigDigger', 'WildMoonThieves', 'LuckyLadyClover']:
            with self.assertRaises(ValueError):
                adapter.metadata(gid, 'unsupported client')
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        before = report('DigDigDigger')['events'][-1]['response']
        before = copy.deepcopy(before)
        before['flow']['available_actions'] = ['init', 'spin']
        with self.assertRaises(ValueError):
            adapter.prepare(before, meta, 'black')

    def test_once_only_claim_survives_uncertain_transport_and_blocks_replay(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        r = report('DigDigDigger')
        credentials = {'fresh_demo': True, 'game_id': 'DigDigDigger', 'operation': {'status': 'received'}, 'last_response': r['events'][-1]['response']}
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / 'new-claim.json'
            def uncertain(command, options=None):
                raise TimeoutError('Synthetic uncertain transport')
            with self.assertRaises(TimeoutError):
                adapter.continue_once(r, credentials, meta, 'black', claim, uncertain, lambda value: value)
            self.assertEqual(json.loads(claim.read_text())['status'], 'dispatching')
            with self.assertRaises(FileExistsError):
                adapter.continue_once(r, credentials, meta, 'black', claim, uncertain, lambda value: value)

    def test_received_success_records_check_and_duplicate_claim_never_dispatches(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        r = report('DigDigDigger')
        current = r['events'][-1]['response']
        credentials = {'fresh_demo': True, 'game_id': 'DigDigDigger', 'operation': {'status': 'received'}, 'last_response': current}
        after = copy.deepcopy(current)
        after.update(gamble={'win': False, 'value': '000h'}, balance={'wallet': 99990, 'game': 0})
        after['flow'].update(command='gamble', state='closed', last_action_id='action-next', available_actions=['init', 'spin'])
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / 'claim.json'
            result = adapter.continue_once(r, credentials, meta, 'black', claim, lambda command, options: after, lambda value: value)
            self.assertEqual(result['check']['effective_balance_native'], 99990)
            self.assertEqual(json.loads(claim.read_text())['status'], 'validated_received')
            with self.assertRaises(FileExistsError):
                adapter.continue_once(r, credentials, meta, 'black', claim, lambda *a: self.fail('Duplicate dispatch'), lambda value: value)

    def test_checkpoint_mismatch_and_nonfun_context_block_before_claim(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        r = report('DigDigDigger')
        credentials = {'fresh_demo': True, 'game_id': 'DigDigDigger', 'operation': {'status': 'received'}, 'last_response': copy.deepcopy(r['events'][-1]['response'])}
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / 'claim.json'
            credentials['last_response']['balance']['wallet'] += 1
            with self.assertRaises(ValueError):
                adapter.continue_once(r, credentials, meta, 'black', claim, lambda *a: self.fail('Unmatched dispatch'), lambda value: value)
            credentials['last_response'] = r['events'][-1]['response']
            changed = copy.deepcopy(r)
            changed['events'][0]['response']['options']['currency']['code'] = 'EUR'
            with self.assertRaises(ValueError):
                adapter.continue_once(changed, credentials, meta, 'black', claim, lambda *a: self.fail('Non-FUN dispatch'), lambda value: value)
            self.assertFalse(claim.exists())

    def test_unowned_or_mismatched_checkpoint_creates_no_claim(self):
        meta = adapter.metadata('DigDigDigger', source('DigDigDigger'))
        r = report('DigDigDigger')
        with tempfile.TemporaryDirectory() as directory:
            claim = Path(directory) / 'new-claim.json'
            credentials = {'fresh_demo': False, 'game_id': 'DigDigDigger', 'operation': {'status': 'received'}, 'last_response': r['events'][-1]['response']}
            with self.assertRaises(ValueError):
                adapter.continue_once(r, credentials, meta, 'black', claim, lambda *a: self.fail('No transport'), lambda value: value)
            self.assertFalse(claim.exists())


if __name__ == '__main__':
    unittest.main()
