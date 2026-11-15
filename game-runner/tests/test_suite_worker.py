"""Offline bridge contract tests: no provider traffic or campaign execution."""
import importlib.util
import json
import os
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

WORKER = Path(__file__).resolve().parents[1] / 'suite_worker.py'
spec = importlib.util.spec_from_file_location('suite_worker', WORKER)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class SuiteBridgeTests(unittest.TestCase):
    def test_spinomenal_uses_configured_native_case_root(self):
        checkout = self.folder / 'checkout'
        checkout.mkdir()
        mode = {'key': 'normal'}
        game = {'id': 'fixture'}
        with patch.dict(os.environ, {'EVIDENCIA_NATIVE_CASE_ROOT': ''}):
            original = bridge.binding('spinomenal', game, mode)
            self.assertEqual(bridge.provider_root(checkout, 'spinomenal'), checkout)
        with patch.dict(os.environ, {'EVIDENCIA_NATIVE_CASE_ROOT': str(self.folder)}):
            self.assertEqual(bridge.provider_root(checkout, 'spinomenal'), self.folder.resolve())
            self.assertNotEqual(bridge.binding('spinomenal', game, mode), original)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / 'native.json').write_text('{"owner":"fictional-fixture-owner","award":"2"}')
        self.case = {'provider': 'elk', 'execution_source': 'native_remote'}
        self.row = dict(status='completed', closed=True, balance_before='10', cost='3', win='2', balance_after='9', currency='EUR', monetary_unit='major')

    def outcome(self, **updates):
        return bridge.normalize_outcome(self.case, dict(self.row, **updates), self.folder, {})

    def test_independent_ledger_ignores_wallet_match_label(self):
        good = self.outcome(wallet_check='pending')
        self.assertTrue(good['checks']['suite_independent_wallet_ledger'])
        bad = self.outcome(wallet_check='match', balance_after='9.01')
        self.assertFalse(bad['checks']['suite_independent_wallet_ledger'])
        self.assertEqual(bad['payout'], '2')

    def test_wallet_flag_alone_not_evidence(self):
        with self.assertRaisesRegex(ValueError, 'missing_or_inexact'):
            bridge.normalize_outcome(self.case, dict(status='completed', closed=True, wallet_check='match'), self.folder, {})

    def test_missing_payout_not_derived_from_wallet(self):
        with self.assertRaises(ValueError):
            self.outcome(win=None)

    def test_exact_tiny_payout_is_not_rounded_away(self):
        value = self.outcome(win='0.0000000000000000000000000001', balance_after='7')
        self.assertFalse(value['checks']['suite_independent_wallet_ledger'])

    def test_float_money_is_rejected(self):
        with self.assertRaises(ValueError):
            self.outcome(win=2.0)

    def test_open_or_conditional_unobserved_not_closed(self):
        for updates in ({'closed': False}, {'closed': None}, {'requested_mode_observed': False}, {'status': 'captured'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.outcome(**updates)

    def test_local_model_is_not_remote_settlement(self):
        with self.assertRaisesRegex(ValueError, 'nonremote'):
            self.outcome(source='local_model')

    def test_currency_and_unit_are_required(self):
        for updates in ({'currency': None}, {'monetary_unit': None}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.outcome(**updates)

    def test_public_currency_binding_is_explicit(self):
        row = dict(self.row)
        del row['currency']
        value = bridge.normalize_outcome(self.case, row, self.folder, {'currency': 'EUR'})
        self.assertEqual(value['currency_source'], 'public_binding')
        with self.assertRaisesRegex(ValueError, 'currency_binding_changed'):
            bridge.normalize_outcome(self.case, self.row, self.folder, {'currency': 'USD'})

    def test_smartsoft_accepts_only_its_native_journal_and_demo_currency(self):
        (self.folder / 'native.json').unlink()
        journal = self.folder / 'smartsoft-native.jsonl'
        journal.write_text('{}\n', encoding='utf8')
        case = dict(self.case, provider='smartsoft')
        row = dict(self.row, currency='DMO')
        settings = bridge.monetary_binding('smartsoft')
        self.assertEqual(bridge.normalize_outcome(case, row, self.folder, settings)['currency'], 'DMO')
        with self.assertRaisesRegex(ValueError, 'currency_binding_changed'):
            bridge.normalize_outcome(case, dict(row, currency='EUR'), self.folder, settings)
        with self.assertRaisesRegex(ValueError, 'owner_and_receipts_missing'):
            bridge.normalize_outcome(self.case, self.row, self.folder, {})

    def test_threeoaks_receipt_requires_native_fun_and_its_own_journal(self):
        (self.folder / 'native.json').unlink()
        (self.folder / 'threeoaks-native.jsonl').write_text('{}\n', encoding='utf8')
        binding = bridge.monetary_binding('threeoaks')
        case = dict(self.case, provider='threeoaks')
        row = {k: v for k, v in self.row.items() if k != 'monetary_unit'}
        receipt = bridge.normalize_outcome(case, dict(row, currency='FUN'), self.folder, binding)
        self.assertEqual((receipt['monetary_unit'], receipt['currency']), ('native', 'FUN'))
        with self.assertRaisesRegex(ValueError, 'currency_binding_changed'):
            bridge.normalize_outcome(case, dict(row, currency='EUR'), self.folder, binding)
        with self.assertRaisesRegex(ValueError, 'owner_and_receipts_missing'):
            self.outcome()

    def test_prerequisite_round_requires_its_own_ledger(self):
        with self.assertRaisesRegex(ValueError, 'prerequisite_ledger_incomplete'):
            self.outcome(prerequisites=[dict(closed=True, wallet_check='match', cost=1, win=0)])

    def test_native_evidence_is_retained_and_hashed(self):
        value = self.outcome()
        item = value['native_data']['evidence'][0]
        self.assertEqual(item['path'], 'native.json')
        self.assertEqual(len(item['sha256']), 64)
        (self.folder / 'native.json').unlink()
        with self.assertRaisesRegex(ValueError, 'owner_and_receipts_missing'):
            self.outcome()

    def test_private_transport_keeps_wire_order_and_does_not_pair_ws_replies(self):
        journal = self.folder / 'transport.jsonl'
        events = [
            dict(event='before_http', sequence=1, method='POST', url='https://demo.example/spin', body='bet=1', phase='financial_or_unknown'),
            dict(event='http_response_headers', sequence=1, status=200),
            dict(event='before_http', sequence=2, method='GET', url='https://demo.example/session', phase='bootstrap'),
            dict(event='http_send_failed', sequence=2, error='Timeout'),
            dict(event='before_ws_connect', url='wss://demo.example/socket', connection=3, phase='bootstrap'),
            dict(event='after_ws_recv', connection=3, payload='heartbeat'),
            dict(event='before_ws_send', connection=3, payload='spin', phase='financial_or_unknown'),
        ]
        journal.write_text(''.join(json.dumps(row) + '\n' for row in events), encoding='utf8')
        steps = self.outcome()['native_data']['transport_steps']
        self.assertEqual([s['stage'] for s in steps], [s['event'] for s in events])
        self.assertEqual(steps[0]['payload'], 'bet=1')
        self.assertEqual(steps[1]['request_sequence'], 1)
        self.assertEqual(steps[1]['http_status'], 200)
        self.assertEqual(steps[3]['error'], 'Timeout')
        self.assertEqual(steps[5]['endpoint'], 'wss://demo.example/socket')
        self.assertNotIn('request_sequence', steps[5])
        self.assertEqual(steps[6]['payload'], 'spin')

    def test_identity_includes_kind_and_prerequisite_policy(self):
        expected = dict(key='buy', type='purchase', requires_prerequisites=True)
        for changed in (dict(expected, type='normal'), dict(expected, requires_prerequisites=False), dict(expected, execution_source='local_model')):
            with self.assertRaisesRegex(ValueError, 'identity_changed'):
                bridge.require_identity(expected, changed)
        bridge.require_identity(expected, dict(expected, label='Localized label'))

    def test_source_missing_and_browser_gaps_are_named(self):
        with patch.object(bridge.importlib.util, 'find_spec', return_value=object()):
            gaps = bridge.prerequisite_gaps(self.folder, 'elk')
            self.assertIn('suite_missing_source:demo-dashboard/elk_client.py', gaps)
            self.assertIn('suite_browser_transport_requires_separate_owner', bridge.prerequisite_gaps(self.folder, 'belatra'))
            self.assertIn('provider_paused_by_user', bridge.prerequisite_gaps(self.folder, 'kendoo'))

    def test_dispatch_marker_is_exclusive(self):
        bridge.durable(self.folder / 'bridge-dispatched.json', {'attempt': 'fixture'})
        with self.assertRaises(FileExistsError):
            bridge.durable(self.folder / 'bridge-dispatched.json', {'attempt': 'replacement'})

    def test_native_binding_hash_includes_control_and_price(self):
        game = dict(id='x', record={'public': 'binding'})
        mode = dict(key='buy', type='purchase', spec={'price': 100})
        self.assertNotEqual(bridge.binding('elk', game, mode), bridge.binding('elk', game, dict(mode, spec={'price': 200})))

    def test_read_preserves_native_json_precision(self):
        path = self.folder / 'result.json'
        path.write_text('{"win":0.1234567890123456789012345678}')
        self.assertEqual(bridge.read(path)['win'], Decimal('0.1234567890123456789012345678'))

    def test_offline_audit_denies_network_and_processes(self):
        for event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'):
            with self.assertRaisesRegex(RuntimeError, 'offline_preflight'):
                bridge.offline_audit(event, ())

    def test_full_synthetic_worker_is_one_shot_and_retains_receipts(self):
        suite = self.folder / 'suite'
        collector = suite / 'bet-collector'
        collector.mkdir(parents=True)
        for name in ('requests', 'websocket'):
            (collector / (name + '.py')).write_text('# offline import fixture\n')
        (collector / 'collection_catalog.py').write_text("""
class Extra:
    SUPPORTED = {'yggdrasil'}
    def load_games(self, provider):
        return [{'id':'fixture', 'name':'Fixture', 'record':{'demo':True},
                 'modes':[{'key':'buy', 'type':'purchase', 'spec':{'price':3}}]}]
EXTRAS = [Extra()]
SUPPORTED = set()
""")
        (collector / 'collection_families.py').write_text("def execution_contract(*args, **kwargs): return {'fixture': True, 'authorizes_execution': False}\n")
        (collector / 'collection_worker.py').write_text("""
import json, sys
from pathlib import Path
folder=Path(sys.argv[1])
(folder/'native.json').write_text(json.dumps({'owner':'fixture', 'award_packet':{'win':'2'}}))
(folder/'result.json').write_text(json.dumps(dict(status='completed',closed=True,
    balance_before='10',balance_after='9',cost='3',win='2',currency='EUR',monetary_unit='major')))
""")
        command = [sys.executable, '-B', str(WORKER), '--suite-root', str(suite)]
        output = subprocess.run(command + ['--capabilities'], capture_output=True, text=True, check=True)
        entry = next(row for row in json.loads(output.stdout)['entries'] if row['provider'] == 'yggdrasil')
        folder = self.folder / 'attempt'
        folder.mkdir()
        request = dict(provider='yggdrasil', game='fixture', mode=entry['mode'],
                       binding_sha256=entry['binding_sha256'], max_prerequisite_rounds=0)
        bridge.durable(folder / 'bridge-request.json', request)
        process = subprocess.run(command + ['--attempt', str(folder)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        outcome = bridge.read(folder / 'bridge-outcome.json')
        self.assertEqual(outcome['payout'], '2')
        self.assertTrue((folder / 'input.json').is_file())
        original = (folder / 'native.json').read_bytes()
        replay = subprocess.run(command + ['--attempt', str(folder)], capture_output=True, text=True)
        self.assertEqual(replay.returncode, 1)
        self.assertEqual((folder / 'native.json').read_bytes(), original)
        self.assertIn('FileExistsError', replay.stderr)

    def test_known_missing_ledgers_are_preflight_gaps(self):
        for provider, record in (('bgaming', {}), ('playtech', {'engine':'gpas'}),
                                 ('habanero', {'family':'portmessage'}), ('irondog', {})):
            gaps = bridge.ledger_contract_gaps(self.folder, provider, {'record':record}, {'key':'normal'})
            self.assertTrue(gaps, provider)
        self.assertEqual(bridge.ledger_contract_gaps(self.folder, 'habanero', {'record':{'family':'play'}}, {'key':'normal'}), [])
        self.assertEqual(bridge.ledger_contract_gaps(self.folder, 'playtech', {'record':{'engine':'gpas'}},
                                                    {'key':'mode-a', 'spec':{'native_id':'mode-a'}}), [])
        self.assertTrue(bridge.ledger_contract_gaps(self.folder, 'playtech', {'record':{'engine':'ngm'}},
                                                   {'key':'NORMAL', 'spec':{'native_id':'NORMAL'}}))

    def test_published_currency_bindings_do_not_invent_unknown_currency(self):
        self.assertEqual(bridge.monetary_binding('yggdrasil')['currency'], 'EUR')
        self.assertEqual(bridge.monetary_binding('mascot')['currency'], 'NAN')
        self.assertNotIn('currency', bridge.monetary_binding('rubyplay'))

    def test_playngo_normalizes_only_native_practice_currency(self):
        binding = bridge.monetary_binding('playngo')
        self.assertEqual(binding, {'currency': 'DEMO', 'currency_source': 'native_response', 'monetary_unit': 'major'})
        case = dict(self.case, provider='playngo')
        verified = bridge.normalize_outcome(case, dict(self.row, currency='DEMO'), self.folder, binding)
        self.assertEqual((verified['currency'], verified['currency_source']), ('DEMO', 'native_response'))
        for currency, error in ((None, 'currency_receipt_missing'), ('EUR', 'currency_binding_changed')):
            with self.assertRaisesRegex(ValueError, error):
                bridge.normalize_outcome(case, dict(self.row, currency=currency), self.folder, binding)

    def test_elk_requires_eur_in_the_settled_native_receipt(self):
        binding = bridge.monetary_binding('elk')
        self.assertEqual(binding, {'currency': 'EUR', 'currency_source': 'native_response', 'monetary_unit': 'major'})
        row = {k: v for k, v in self.row.items() if k != 'monetary_unit'}
        outcome = bridge.normalize_outcome(self.case, row, self.folder, binding)
        self.assertEqual((outcome['currency'], outcome['currency_source']), ('EUR', 'native_response'))
        for currency, error in ((None, 'currency_receipt_missing'), ('USD', 'currency_binding_changed')):
            with self.assertRaisesRegex(ValueError, error):
                bridge.normalize_outcome(self.case, dict(row, currency=currency), self.folder, binding)

    def test_nolimit_settles_native_payout_to_cents_without_using_wallet_delta(self):
        case = dict(self.case, provider='nolimit')
        binding = bridge.monetary_binding('nolimit')
        self.assertEqual(binding.get('currency'), 'EUR')
        row = dict(self.row, win='2.009', closed_next_mode='NORMAL', extra_spin_costs='0',
                   settlement_rule='truncate_final_balance_2dp', settled_win='999')
        outcome = bridge.normalize_outcome(case, row, self.folder, binding)
        self.assertEqual(outcome['payout'], '2.00')
        self.assertTrue(outcome['checks']['suite_independent_wallet_ledger'])
        mismatch = bridge.normalize_outcome(case, dict(row, balance_after='9.01'), self.folder, binding)
        self.assertFalse(mismatch['checks']['suite_independent_wallet_ledger'])
        for update in ({'closed_next_mode': 'FREESPIN'}, {'extra_spin_costs': '1'},
                       {'settlement_rule': 'unknown'}, {'cost': '3.001'}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'nolimit_settlement'):
                bridge.normalize_outcome(case, dict(row, **update), self.folder, binding)

    def test_mascot_rejects_ambiguous_native_awards_without_wallet_selection(self):
        collector = WORKER.parent.parent / 'bet-collector'
        sys.path.insert(0, str(collector))
        self.addCleanup(lambda: sys.path.remove(str(collector)))
        import collection_mascot as mascot
        entry = {'action':'spin','bet':1,'boost':False}
        mode = {'key':'normal','type':'normal','spec':{'entry':entry,'cost':1}}
        initial = dict(gameId=7,currency='NAN',feature='basic',nextAction='spin',
                       betCoins=1,bets=[1],balance=10)
        final = dict(gameId=7,currency='NAN',feature='basic',nextAction='spin',
                     bet=1,balance=11,totalWin=2,win=3)
        bank = dict(gameId=7,key='g',demo_id='d',init=initial,
                    rounds=[{'cost':1,'steps':[{'request':entry,'response':final}]}])
        case = dict(provider='mascot',game_id='g',game={'demo_id':'d','native_id':7,'bank_sha256':'fixture'},mode=mode)
        with patch.object(mascot, 'load_bank', return_value=(bank,'fixture')):
            with patch.object(mascot, 'bank_modes', return_value={'normal':mode}):
                result = mascot.execute_round(case, lambda body: initial if body['action']=='init' else final)
        self.assertEqual(result['reason'], 'mascot_native_payout_ambiguous')
        self.assertIsNone(result['win'])
        final['win'] = 2
        with patch.object(mascot, 'load_bank', return_value=(bank,'fixture')):
            with patch.object(mascot, 'bank_modes', return_value={'normal':mode}):
                result = mascot.execute_round(case, lambda body: initial if body['action']=='init' else final)
        self.assertEqual(result['win'], 2)
        self.assertEqual(result['monetary_unit'], 'native')

    def test_ruby_receipts_expose_each_native_prerequisite_ledger(self):
        collector = WORKER.parent.parent / 'bet-collector'
        sys.path.insert(0, str(collector))
        self.addCleanup(lambda: sys.path.remove(str(collector)))
        import collection_full_node as node
        accounting = {'prerequisite_rounds':[{'mode':'normal','cash_debit_native':'1',
            'cash_payout_native':'2','balance_before_native':'10','balance_after_native':'11',
            'wallet_check':'match','evidence':'fixture.json'}]}
        result = node.ruby_prerequisites(accounting)[0]
        self.assertEqual(result['balance_before'], '10')
        self.assertEqual(result['balance_after'], '11')
        self.assertEqual(result['win'], '2')

    def test_explicit_uncertain_or_omitted_paid_roots_are_rejected(self):
        for accounting in ({'uncertain_paid_roots':[{'root':'pending'}]},
                           {'requested_mode_observed':True,'paid_root_attempts':2,'closed_paid_roots':1,
                            'requested_rounds':[{}],'all_paid_rounds':[{}]}):
            with self.subTest(accounting=accounting), self.assertRaisesRegex(ValueError, 'paid_root_accounting'):
                self.outcome(accounting=accounting)

    def test_ruby_accounting_requires_a_journal_for_every_closed_step(self):
        collector = WORKER.parent.parent / 'bet-collector'
        sys.path.insert(0, str(collector))
        self.addCleanup(lambda: sys.path.remove(str(collector)))
        import collection_full_node as node
        results = self.folder / 'results'
        prep = self.folder / 'private/live/rp_29-preparation'
        results.mkdir()
        prep.mkdir(parents=True)
        row = dict(mode='ruby_buy', finished=True, root_balance=10, final_balance=11,
                   steps=[dict(key='ruby-purchase-0001', action=9, cost=1, paid_win=2, wallet_matches=True)])
        receipt = results / 'rp_29-ruby-purchase.json'
        node.write(receipt, row)
        self.assertFalse(node.ruby_accounting(self.folder, 'rp_29', 'ruby_buy')['requested_mode_observed'])
        journal = prep / 'ruby-purchase-0001.journal.json'
        plan = dict(key='ruby-purchase-0001', mode='ruby_buy', native_cost=1, before_balance=10)
        node.write(journal, dict(state='received', status=200, native_plan=plan))
        self.assertTrue(node.ruby_accounting(self.folder, 'rp_29', 'ruby_buy')['requested_mode_observed'])
        node.write(journal, dict(state='intent_before_send', native_plan=plan))
        accounting = node.ruby_accounting(self.folder, 'rp_29', 'ruby_buy')
        self.assertFalse(accounting['requested_mode_observed'])
        self.assertEqual(len(accounting['uncertain_paid_roots']), 1)

    def test_prerequisite_ledgers_must_chain_to_requested_owner(self):
        prerequisite = dict(closed=True,balance_before='20',balance_after='19',cost='1',win='0')
        with self.assertRaisesRegex(ValueError, 'not_chained'):
            self.outcome(prerequisites=[prerequisite])
        prerequisite.update(balance_before='11',balance_after='10')
        self.assertTrue(self.outcome(prerequisites=[prerequisite])['checks']['suite_prerequisite_ledgers'])

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel Job Object integration')
    def test_windows_job_kills_descendant_on_parent_exit_and_termination(self):
        for termination in (False, True):
            with self.subTest(termination=termination):
                marker = self.folder / ('marker-' + str(termination))
                ready = self.folder / ('ready-' + str(termination))
                script = r"""import importlib.util,subprocess,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('bridge',sys.argv[1])
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
bridge.install_process_job()
subprocess.Popen([sys.executable,'-c','import sys,time;from pathlib import Path;time.sleep(2);Path(sys.argv[1]).write_text("unsafe")',sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(sys.argv[3]).write_text('ready')
if sys.argv[4]=='terminate':time.sleep(30)
"""
                process = subprocess.Popen([sys.executable,'-B','-c',script,str(WORKER),str(marker),str(ready),
                                            'terminate' if termination else 'normal'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(ready.exists(), 'Job assignment or child startup failed')
                    if termination:
                        process.kill()
                    stdout, stderr = process.communicate(timeout=10)
                    if not termination:
                        self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
                    time.sleep(2.3)
                    self.assertFalse(marker.exists(), 'descendant escaped Job Object lifetime')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=10)

    def test_missing_suite_fails_without_dispatch(self):
        result = subprocess.run([sys.executable, '-B', str(WORKER), '--suite-root', str(self.folder), '--capabilities'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('suite_collection_worker_missing', result.stderr)


if __name__ == '__main__':
    unittest.main()
