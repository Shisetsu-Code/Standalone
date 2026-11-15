import unittest,json,copy
from pathlib import Path
import native
ROOT=Path(__file__).resolve().parent.parent
class AuditTests(unittest.TestCase):
    def test_captured_rounds_and_purchase_close_with_exact_credit(self):
        packets=json.loads((ROOT/'private/captured-api.json').read_text())
        result=native.audit_packets(packets)
        self.assertEqual(len(result['closed_rounds']),15)
        self.assertEqual(result['unfinished_rounds'],[])
        buy=next(r for r in result['closed_rounds'] if r['mode']=='BUY_BONUS')
        self.assertEqual((buy['cost_cents'],buy['payout_cents'],buy['balance_after_cents']),(1200,968,9999728))
    def test_modified_credit_is_rejected(self):
        packets=json.loads((ROOT/'private/captured-api.json').read_text());p=next(p for p in packets if p['endpoint']=='_Roll');p['response']['Balance']['ScoreCents']+=1
        with self.assertRaisesRegex(ValueError,'balance'):native.audit_packets(packets)
    def test_unconfirmed_http_never_counts_as_closed(self):
        packets=json.loads((ROOT/'private/captured-api.json').read_text());p=next(p for p in packets if p['endpoint']=='_Roll');p['http_status']=500
        with self.assertRaises(ValueError):native.audit_packets(packets)
    def test_omitted_accept_flag_is_terminal_only_when_init_disables_gamble(self):
        packets=json.loads((ROOT/'private/captured-api.json').read_text())[:2]
        packets[1]['response'].pop('waitForAcceptWin')
        self.assertEqual(len(native.audit_packets(packets)['closed_rounds']),1)
        packets[0]['response']['GameSettings']['IsGambleAllowed']=True
        self.assertEqual(len(native.audit_packets(packets)['closed_rounds']),0)
    def test_native_accept_win_closes_only_the_offered_exact_credit(self):
        c=json.loads((ROOT/'private/rounds/bookofgames20/BUY_BONUS.json').read_text());init=json.loads(Path(c['source_init_reference']).read_text());init['response']['Balance']['ScoreCents']=c['balance_before_cents']
        packets=[init]+[p for p in c['journal'] if p['endpoint']!='_AcceptWin']
        expected=native.number(c['balance_before_cents'])-native.number(c['expected_cost_cents'])+native.number(packets[-1]['response']['roundWin'])
        packets.append({'endpoint':'_AcceptWin','http_status':200,'session_fingerprint':c['session_fingerprint'],'game':c['game'],'request':{'sid':'[REDACTED]'},'response':{'Balance':{'ScoreCents':expected,'Currency':'EUR'}}})
        self.assertEqual(native.audit_packets(packets)['closed_rounds'][0]['balance_after_cents'],expected)
        packets[-1]['response']['Balance']['ScoreCents']+=1
        with self.assertRaisesRegex(ValueError,'balance'):native.audit_packets(packets)
    def test_indian_pick_uses_native_summary_when_round_win_is_omitted(self):
        c=json.loads((ROOT/'private/rounds/indiancall/BUY_LowBonus.json').read_text());init=json.loads(Path(c['source_init_reference']).read_text());init['response']['Balance']['ScoreCents']=c['balance_before_cents'];packets=[init]+c['journal'][:2]
        self.assertEqual(len(native.audit_packets(packets)['unfinished_rounds']),1)
        row=next(v for v in packets[-1]['response']['Variables'] if v['Name']=='SummaryWinCents');row['Value']='1'
        with self.assertRaisesRegex(ValueError,'round_win'):native.audit_packets(packets)
    def test_gamble_replaces_held_win_without_double_counting(self):
        c=json.loads((ROOT/'private/rounds/bookofgames20/BUY_BONUS.json').read_text());init=json.loads(Path(c['source_init_reference']).read_text());init['response']['Balance']['ScoreCents']=c['balance_before_cents'];base=[init]+[p for p in c['journal'] if p['endpoint']!='_AcceptWin'];held=base[-1]['response']['Balance']['ScoreCents'];old=base[-1]['response']['roundWin']
        for win in [True,False]:
            packets=copy.deepcopy(base);payout=old*2 if win else 0
            packets.append({'endpoint':'_Gamble','game':c['game'],'session_fingerprint':c['session_fingerprint'],'http_status':200,'request':{'sid':'[REDACTED]','data':0},'response':{'Gamble':{'IsWin':win},'Balance':{'ScoreCents':held,'TotalWinCents':payout,'Currency':'EUR'}}})
            if win:packets.append({'endpoint':'_AcceptWin','game':c['game'],'session_fingerprint':c['session_fingerprint'],'http_status':200,'request':{'sid':'[REDACTED]'},'response':{'Balance':{'ScoreCents':held+payout,'Currency':'EUR'}}})
            result=native.audit_packets(packets)['closed_rounds'][0];self.assertEqual(result['payout_cents'],payout);self.assertEqual(result['mode'],'GAMBLE')
