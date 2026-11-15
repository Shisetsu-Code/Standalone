import json,unittest
from pathlib import Path
from old_slots import plan,metadata,closed_result,paid_result,free_result,free_spin_wire
P=Path(__file__).parent
class OldSlots(unittest.TestCase):
 def test_book_minimum_line_dictionary_uses_native_units(self):
  initial=json.loads((P/'live/BookOfCats.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(initial,{'source_verified':True})[0];self.assertEqual(m['cost_native'],10);self.assertEqual(m['line_bet_native'],1);self.assertEqual(m['options'],{'bets':{str(i):1 for i in range(10)}})
 def test_elvis_default_lines_and_minimum(self):
  initial=json.loads((P/'live/ElvisFrog.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(initial,{'source_verified':True})[0];self.assertEqual(m['cost_native'],250);self.assertEqual(m['line_count'],25)
 def test_unsupported_source_is_not_guessed(self):
  with self.assertRaises(ValueError):metadata('unknown client')
 def test_received_book_loss_closes_without_replaying_spin(self):
  fixture=json.loads((P/'BookOfCats.normal-loss.reference.json').read_text(encoding='utf8'));initial=fixture['before'];mode={'cost_native':10}
  result=closed_result(initial,fixture['event']['response'],mode,{'v1_result_total_verified':True})
  self.assertEqual(result['win_native'],0);self.assertEqual(result['final_balance'],99990)
 def test_native_result_total_and_wallet_are_both_checked(self):
  mode={'cost_native':10};meta={'v1_result_total_verified':True};old={'balance':1000}
  r={'balance':1015,'game':{'state':'closed'},'result':{'total':25}}
  self.assertEqual(closed_result(old,r,mode,meta)['win_native'],25)
  r['balance']=1014
  with self.assertRaises(ValueError):closed_result(old,r,mode,meta)
 def test_bonus_state_is_preserved_without_guessing_continuations(self):
  with self.assertRaises(ValueError):closed_result({'balance':1000},{'balance':990,'game':{'state':'freespin'}},{'cost_native':10},{'v1_result_total_verified':True})
 def test_main_planner_dispatches_native_v1_lines(self):
  from run_demo_qa import modes_from_init
  initial=json.loads((P/'live/BookOfCats.json').read_text(encoding='utf8'))['events'][0]['response']
  self.assertEqual(modes_from_init(initial,{'protocol':'legacy-v1-slots','source_verified':True})[0]['cost_native'],10)
 def test_pending_gamble_money_can_be_verified_without_claiming_round_closed(self):
  response={'balance':99991,'game':{'state':'check_card'},'result':{'total':6},'available_commands':['check_card','finish','init']};result=paid_result({'balance':100000},response,{'cost_native':15},{'v1_result_total_verified':True});self.assertEqual(result['status'],'open');self.assertEqual(result['win_native'],6)
 def test_source_verified_collect_closes_but_keeps_unexercised_gamble_pending(self):
  from run_demo_qa import Demo
  d=Demo({'game_id':'Example'});d.protocol_metadata={'v1_result_total_verified':True,'finish_command_verified':True};old={'balance':1000,'available_commands':['spin']};mode={'command':'spin','options':{'bets':{'0':10}},'cost_native':10};responses=[{'balance':1015,'result':{'total':25},'game':{'state':'check_card'},'available_commands':['init','check_card','finish']},{'balance':1015,'game':{'state':'closed'},'available_commands':['init','spin']}];calls=[]
  def call(command,options=None):calls.append((command,options));d.events.append({});return responses.pop(0)
  d.call=call
  from old_slots import run_mode
  result=run_mode(d,mode,old);self.assertEqual([c[0] for c in calls],['spin','finish']);self.assertEqual(result['win_native'],25);self.assertEqual(result['final_balance'],1015);self.assertTrue(d.protocol_metadata['unresolved'])
 def test_source_proved_book_purchase_uses_native_line_bets_and_flag(self):
  a=json.loads((P/'live/BookOfCats.json').read_text(encoding='utf8'))['events'][0]['response'];modes=plan(a,{'source_verified':True,'v1_buy_feature_verified':True});self.assertEqual(len(modes),2);self.assertEqual(modes[1]['cost_native'],970);self.assertTrue(modes[1]['options']['buy_feature']);self.assertEqual(modes[1]['options']['bets'],modes[0]['options']['bets'])
 def test_free_spin_has_zero_debit_and_never_repeats_purchase_flag(self):
  before={'balance':99050,'game':{'state':'freespin','freespins_left':10},'bets':{'lines':{'0':1}},'available_commands':['init','spin']};response={'balance':99056,'result':{'total':6},'game':{'state':'freespin','freespins_left':9}};meta={'v1_freespin_spin_verified':True,'v1_result_total_verified':True}
  self.assertEqual(free_result(before,response,{'bets':{'0':1}},meta)['check']['cost_native'],0)
  with self.assertRaises(ValueError):free_result(before,response,{'bets':{'0':1},'buy_feature':True},meta)
  before['game']['freespins_left']=0
  with self.assertRaises(ValueError):free_result(before,response,{'bets':{'0':1}},meta)
 def test_source_free_flag_only_changes_v2_command(self):
  self.assertTrue(free_spin_wire('if(A.isApi2)e&&(q.command="freespin");else{p.bets=c}'))
  self.assertFalse(free_spin_wire('if(A.isApi2)e&&(q.command="freespin");else{p.bets=e}'))
 def test_free_spin_missing_total_preserves_native_cumulative_field(self):
  fixture=json.loads((P/'BookOfCats.first-free-zero.reference.json').read_text(encoding='utf8'));meta={'v1_freespin_spin_verified':True,'v1_result_total_verified':True,'v1_round_total_verified':True};result=free_result(fixture['before'],fixture['event']['response'],fixture['event']['request']['options'],meta);self.assertEqual(result['win_native'],0);self.assertEqual(result['win_origin'],'native_round_total_delta');self.assertNotIn('total',fixture['event']['response']['result'])
  fixture['event']['response']['result']['round_total_win']=26
  with self.assertRaises(ValueError):free_result(fixture['before'],fixture['event']['response'],fixture['event']['request']['options'],meta)
if __name__=='__main__':unittest.main()
