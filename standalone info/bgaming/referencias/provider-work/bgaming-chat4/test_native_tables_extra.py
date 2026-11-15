"""Offline source and synthetic native-wallet lifecycle checks; no transport."""
import copy
import importlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT.parents[1] / 'bgaming-private-chat4'


def initial(gid):
    return json.loads((ROOT / 'live' / (gid + '.json')).read_text())['events'][0]['response']


def source(gid):
    p = (PRIVATE / 'research/classic/casino.min.js' if gid.startswith('Minesweeper') else
         next((PRIVATE / 'research/legacy' / gid).glob('*/bundle.js')))
    return p.read_text(encoding='utf8')


class NativeTablesTests(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module('native_tables_extra')

    def test_all_dice_thresholds_and_twenty_risk_choices(self):
        for gid in ['RocketDice', 'RocketDiceXY']:
            modes = self.m.plan(initial(gid), self.m.metadata(source(gid), gid))
            self.assertEqual(len(modes), 40)
            self.assertEqual(len({tuple(x['risk_chosen']) for x in modes if 'risk_chosen' in x}), 20)
            base = [x for x in modes if 'risk_chosen' not in x]
            self.assertEqual({(x['options']['kind'], x['options']['score']) for x in base},
                             {(k, int(s)) for k, v in initial(gid)['paytable'].items() for s in v})
            self.assertTrue(all(x['cost_native'] == 100 for x in modes))

    def test_mine_row_position_modes_cover_advertised_field(self):
        for gid in ['MineGems', 'FortuneRedPackets', 'Minesweeper', 'MinesweeperXY']:
            modes = self.m.plan(initial(gid), self.m.metadata(source(gid), gid))
            expected = sum(int(f.split('x')[0]) * int(f.split('x')[1]) for f in initial(gid)['options']['fields'])
            self.assertEqual(len(modes), expected)
            self.assertTrue(all(x['options']['bet'] == 100 for x in modes))

    def test_mine_held_win_is_not_credited_until_stop(self):
        check = self.m.reconcile(100000, {'balance':99900, 'game':{'state':'alive','step_win':123}}, 100)
        self.assertEqual(check['win_native'], 0)
        self.assertEqual(self.m.reconcile(99900, {'balance':100023,'result':123,'game':{'state':'closed'}},0)['win_native'],123)
        with self.assertRaises(ValueError):
            self.m.reconcile(99900, {'balance':100023,'result':246,'game':{'state':'closed'}},0)

    def test_null_loss_zero_prize_and_fractional_wallet_rejection(self):
        self.assertEqual(self.m.reconcile(1000, {'balance':900,'result':None,'game':{'state':'closed'}},100)['win_native'],0)
        with self.assertRaises(ValueError):
            self.m.reconcile(1000, {'balance':900.0,'result':None,'game':{'state':'closed'}},100)

    def test_fail_closed_unproved_source_and_non_fun(self):
        with self.assertRaises(ValueError): self.m.metadata('command:"start"', 'MineGems')
        i = copy.deepcopy(initial('RocketDice')); i['options']['currency']['code']='USD'
        with self.assertRaises(ValueError): self.m.plan(i, self.m.metadata(source('RocketDice'),'RocketDice'))

    def test_mine_lifecycle_stop_does_not_send_bet(self):
        i = initial('MineGems'); mode = self.m.plan(i,self.m.metadata(source('MineGems'),'MineGems'))[0]
        d = FakeDemo(i,[{'balance':99900,'game':{'state':'alive','step_win':123},'available_commands':['step','stop']},
                        {'balance':100023,'result':123,'game':{'state':'closed'},'available_commands':['start']}])
        r = self.m.run(d, mode, i)
        self.assertEqual(r['status'],'closed'); self.assertEqual(d.requests[-1],('stop',None))
        self.assertEqual(len(d.money_checks),2)

    def test_dice_finish_loss_no_unadvertised_followup(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'risk','win':0},'available_commands':['finish']},
                      {'balance':99900,'result':None,'game':{'state':'closed'},'available_commands':['roll']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'closed')
        self.assertEqual(d.requests[-1],('finish',None))

    def test_conditional_risk_not_falsely_reported_complete(self):
        i=initial('RocketDice');mode=next(x for x in self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice')) if 'risk_chosen' in x)
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'closed'},'available_commands':['roll']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'needs_trigger')

    def test_unadvertised_step_stops_before_transport(self):
        i=initial('MineGems');mode=self.m.plan(i,self.m.metadata(source('MineGems'),'MineGems'))[1]
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'alive'},'available_commands':['stop']}])
        with self.assertRaises(ValueError): self.m.run(d,mode,i)
        self.assertEqual(len(d.requests),1)

    def test_successful_risk_replaces_held_award_and_credits_once(self):
        i=initial('RocketDice');mode=next(x for x in self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice')) if 'risk_chosen' in x)
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'risk','win':101},'available_commands':['risk','finish']},
                      {'balance':99900,'game':{'state':'risk','win':202},'available_commands':['risk','finish']},
                      {'balance':99900,'result':202,'game':{'state':'closed','action':'finish'},'available_commands':['roll']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'closed')
        self.assertEqual(d.requests[1],('risk',{'chosen':mode['risk_chosen']}))
        self.assertEqual([c['cost_native'] for c in d.money_checks],[100,0,0])
        self.assertEqual([c['win_native'] for c in d.money_checks],[0,0,202])

    def test_bad_protocol_is_rejected_before_paid_request(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        mode['protocol']='unknown';d=FakeDemo(i,[])
        with self.assertRaises(ValueError):self.m.run(d,mode,i)
        self.assertEqual(d.requests,[])

    def test_wallet_mismatch_retains_exact_response_before_error(self):
        i=initial('MineGems');mode=self.m.plan(i,self.m.metadata(source('MineGems'),'MineGems'))[0]
        bad={'balance':999.0,'game':{'state':'alive'},'available_commands':['stop']};d=FakeDemo(i,[bad])
        with self.assertRaises(ValueError):self.m.run(d,mode,i)
        self.assertIs(d.prev,bad)

    def test_lost_continuation_depth_target_is_not_complete(self):
        i=initial('MineGems');mode=self.m.plan(i,self.m.metadata(source('MineGems'),'MineGems'))[1]
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'alive','step_win':123},'available_commands':['step','stop']},
                      {'balance':99900,'result':None,'game':{'state':'closed'},'available_commands':['start']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'needs_trigger')

    def test_first_step_selector_loss_is_exercised(self):
        i=initial('MineGems');mode=self.m.plan(i,self.m.metadata(source('MineGems'),'MineGems'))[0]
        self.assertEqual(mode['target_kind'],'first_step_selector')
        d=FakeDemo(i,[{'balance':99900,'result':None,'game':{'state':'closed'},'available_commands':['start']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'closed')

    def test_dice_finished_with_roll_is_terminal_without_extra_finish(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        d=FakeDemo(i,[{'balance':99900,'result':None,'game':{'state':'finished','win':0},'available_commands':['init','roll']}])
        result=self.m.run(d,mode,i)
        self.assertEqual(result['status'],'closed');self.assertEqual(result['final_state'],'finished')
        self.assertEqual(len(d.requests),1)

    def test_dice_finished_with_only_finish_is_not_terminal(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        d=FakeDemo(i,[{'balance':99900,'game':{'state':'finished','win':0},'available_commands':['finish']},
                      {'balance':99900,'game':{'state':'finished','win':0},'available_commands':['roll']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'closed')
        self.assertEqual(d.requests[-1],('finish',None))

    def test_dice_finished_without_roll_cannot_begin_new_paid_round(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        d=FakeDemo({'balance':99900,'game':{'state':'finished'},'available_commands':['finish']},[])
        with self.assertRaises(ValueError):self.m.run(d,mode,i)
        self.assertEqual(d.requests,[])

    def test_dice_finished_with_roll_can_begin_next_paid_round(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        d=FakeDemo({'balance':99900,'game':{'state':'finished'},'available_commands':['roll']},
                   [{'balance':99800,'game':{'state':'finished'},'available_commands':['roll']}])
        self.assertEqual(self.m.run(d,mode,i)['status'],'closed');self.assertEqual(len(d.requests),1)

    def test_actual_xy_finish_keeps_raw_balance_and_proves_pending_prize(self):
        before={'bets':{'roll':100},'game':{'outcome':[3,4],'win':101,'state':'risk','action':'roll'},'balance':99900,'available_commands':['finish','init','risk']}
        finish={'game':{'state':'closed','action':'finish'},'result':101,'balance':99900,'available_commands':['init','roll']}
        original=copy.deepcopy(finish)
        check=self.m.reconcile(before,finish,0,protocol='native-rocket-dice',command='finish')
        self.assertEqual(check['raw_actual_native'],99900)
        self.assertEqual(check['pending_credit_after_native'],101)
        self.assertEqual(check['expected'],100001);self.assertEqual(check['actual'],100001)
        self.assertEqual(finish,original)

    def test_next_roll_credits_previous_finished_prize_exactly_once(self):
        finish={'game':{'state':'closed','action':'finish'},'result':101,'balance':99900,'available_commands':['init','roll']}
        next_roll={'game':{'state':'risk','action':'roll','win':0},'balance':99901,'available_commands':['finish']}
        check=self.m.reconcile(finish,next_roll,100,protocol='native-rocket-dice',command='roll')
        self.assertEqual(check['pending_credit_before_native'],101);self.assertEqual(check['pending_credit_after_native'],0)
        self.assertEqual(check['raw_expected_native'],99901);self.assertEqual(check['raw_actual_native'],99901)
        finish2={'game':{'state':'closed','action':'finish'},'result':None,'balance':99901,'available_commands':['roll']}
        check2=self.m.reconcile(next_roll,finish2,0,protocol='native-rocket-dice',command='finish')
        self.assertEqual(check2['actual'],99901)

    def test_finish_prize_must_match_original_held_game_win(self):
        roll={'balance':99900,'game':{'state':'risk','action':'roll','win':101},'available_commands':['finish']}
        finish={'balance':99900,'result':102,'game':{'state':'closed','action':'finish'},'available_commands':['roll']}
        with self.assertRaises(ValueError):self.m.reconcile(roll,finish,0,protocol='native-rocket-dice',command='finish')

    def test_already_credited_finish_balance_is_not_silently_adjusted(self):
        roll={'balance':99900,'game':{'state':'risk','action':'roll','win':101},'available_commands':['finish']}
        finish={'balance':100001,'result':101,'game':{'state':'closed','action':'finish'},'available_commands':['roll']}
        with self.assertRaises(ValueError):self.m.reconcile(roll,finish,0,protocol='native-rocket-dice',command='finish')

    def test_run_uses_effective_pending_credit_for_affordability(self):
        i=initial('RocketDice');mode=self.m.plan(i,self.m.metadata(source('RocketDice'),'RocketDice'))[0]
        previous={'balance':0,'result':101,'game':{'state':'closed','action':'finish'},'available_commands':['roll']}
        d=FakeDemo(previous,[{'balance':1,'game':{'state':'finished','action':'roll','win':0},'available_commands':['roll']}])
        result=self.m.run(d,mode,i)
        self.assertEqual(len(d.requests),1);self.assertEqual(result['final_balance'],1)
        self.assertEqual(result['final_effective_balance_native'],1)


class FakeDemo:
    def __init__(self, initial, responses):
        self.prev=initial; self.responses=iter(responses);self.events=[];self.requests=[];self.money_checks=[]
    def call(self,command,options=None):
        self.requests.append((command,options));response=next(self.responses);self.events.append({'response':response});return response


if __name__=='__main__': unittest.main()
