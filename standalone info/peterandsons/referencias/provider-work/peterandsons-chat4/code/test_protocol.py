import copy
import json
from pathlib import Path
import unittest
import protocol
from protocol import audit_round,minimum_modes
ROOT=Path(__file__).resolve().parent.parent

def cycles():
    for trace in json.loads((ROOT/'private/captured-api.json').read_text(encoding='utf8')):
        balance=None;info=None;pending=None
        for entry in trace['operations']:
            if entry['path']=='/authenticate':balance=entry['response']['balance']
            elif entry['path']=='/game/info':info=entry['response']
            elif entry['path']=='/game/play':pending=(balance,info,entry)
            elif entry['path']=='/game/complete':
                before,game_info,play=pending
                yield before,game_info,play['request'],play['response'],entry['request'],entry['response']
                balance=entry['response']['balance'];pending=None

class NativeProtocolTests(unittest.TestCase):
    def test_all_sixteen_captured_cycles_reconcile(self):
        data=list(cycles());self.assertEqual(len(data),16)
        self.assertTrue(all(audit_round(*row)['passed'] for row in data))

    def test_native_minimums_and_special_modes(self):
        royal=next(row for row in cycles() if row[2]['game']=='royal-hunt')
        modes={m['id']:m['bet'] for m in minimum_modes(royal[1])}
        self.assertEqual(modes,{'main':0.1,'buy_FS_RAND':7.0,'bet_GUN6':1.8,'bet_3GUNS':4.0,'bet_FREQ':0.15})

    def test_changed_balance_and_incomplete_bonus_are_rejected(self):
        row=list(next(cycles()));row[-1]=copy.deepcopy(row[-1]);row[-1]['balance']+=1
        with self.assertRaisesRegex(ValueError,'balance_mismatch'):audit_round(*row)
        row=list(next(cycles()));row[3]=copy.deepcopy(row[3]);row[3]['wager']['next']=['unknown-choice']
        with self.assertRaisesRegex(ValueError,'not_closed'):audit_round(*row)

    def test_bare_bet_action_requires_native_special_configuration(self):
        path=next((ROOT/'private/sessions').glob('gold-raiders-*/information.json'))
        info=json.loads(path.read_text())['response']
        modes={m['id']:m for m in minimum_modes(info)}
        self.assertEqual(modes['bet']['kind'],'special')
        self.assertEqual(modes['bet']['bet'],0.15)
        self.assertEqual(len(modes),5)
        altered=copy.deepcopy(info);del altered['config']['special_bets_configuration']
        with self.assertRaises(ValueError):minimum_modes(altered)

    def test_action_name_cannot_escape_journal_folder(self):
        info={'bets':{'main':{'available':[0.1]},'buy_../../escape':{'available':[1]}}}
        with self.assertRaises(ValueError):minimum_modes(info)

    def test_bare_buy_requires_native_purchase_configuration(self):
        path=next((ROOT/'private/sessions').glob('viking-legacy-*/information.json'))
        info=json.loads(path.read_text())['response']
        modes={m['id']:m for m in minimum_modes(info)}
        self.assertEqual(modes['buy']['kind'],'purchase')
        self.assertEqual(modes['buy']['bet'],5)
        altered=copy.deepcopy(info);del altered['config']['buy_configuration']
        with self.assertRaises(ValueError):minimum_modes(altered)

    def test_explicit_settlement_rejection_requires_exact_round_binding(self):
        case=json.loads((ROOT/'private/rounds/inks-pints--buy_JACKPOT.json').read_text())
        journal=json.loads((ROOT/'private/sessions'/case['session']/'buy_JACKPOT-complete.json').read_text())
        self.assertTrue(protocol.settlement_rejected(case['play_response'],journal))
        altered=copy.deepcopy(journal);altered['request']['roundId']='different'
        self.assertFalse(protocol.settlement_rejected(case['play_response'],altered))
        altered=copy.deepcopy(journal);altered['http_status']=503
        self.assertFalse(protocol.settlement_rejected(case['play_response'],altered))

    def test_take_round_uses_advertised_next_action_and_existing_round(self):
        case=json.loads((ROOT/'private/rounds/bloody-mary--buy_FS_3SC.json').read_text())
        body=protocol.take_round_request(case['game'],case['play_response'])
        self.assertEqual(body['action'],'take_round')
        self.assertEqual(body['roundId'],case['play_response']['roundId'])
        self.assertNotIn('bet',body)
        altered=copy.deepcopy(case['play_response']);altered['wager']['next']=['extra_spin_fs']
        with self.assertRaises(ValueError):protocol.take_round_request(case['game'],altered)

    def test_take_continuation_does_not_duplicate_bonus_payout(self):
        case=json.loads((ROOT/'private/rounds/bloody-mary--buy_FS_3SC.json').read_text())
        complete_body={'game':case['game'],'provider':'peterandsons','roundId':case['play_response']['roundId'],'asyncWin':False}
        reply={'finalWin':2.5,'balance':9992.26}
        audited=audit_round(case['balance_before'],json.loads((ROOT/'private/plans/bloody-mary.json').read_text())['info'],
            case['play_request'],case['play_response'],complete_body,reply,continuations=case['continuations'])
        self.assertEqual(audited['payout'],2.5)
        self.assertEqual(audited['internal_steps'],10)

if __name__=='__main__':unittest.main()
