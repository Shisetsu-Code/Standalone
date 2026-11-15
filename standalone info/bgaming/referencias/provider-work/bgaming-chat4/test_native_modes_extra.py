"""Offline native payload and original wallet regression checks."""
import importlib
import json
import copy
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parents[1]/'bgaming-private-chat4/research/legacy'

def initial(gid):return json.loads((ROOT/'live'/(gid+'.json')).read_text())['events'][0]['response']
def source(gid):return next((PRIVATE/gid).glob('*/bundle.js')).read_text(encoding='utf8')

def report(gid,steps):
 return {'game':{'game_id':gid},'protocol':'native-modes-extra','status':'testing',
         'events':[{'request':{'command':'init'},'response':initial(gid),'status':200}]+[
          {'request':q,'response':r,'status':200} for q,r in steps], 'modes':[],
         'checks':[{'cost_native':999999,'ok':True}]}

class NativeModesExtraTests(unittest.TestCase):
 def setUp(self):self.m=importlib.import_module('native_modes_extra')
 def modes(self,gid):return self.m.plan(initial(gid),self.m.metadata(source(gid),gid))
 def test_source_gates_and_non_fun_rejected(self):
  with self.assertRaises(ValueError):self.m.metadata('command:"play"','InfinityPull')
  i=initial('ChickenRush2');i['options']['currency']['code']='USD'
  with self.assertRaises(ValueError):self.m.plan(i,self.m.metadata(source('ChickenRush2'),'ChickenRush2'))
 def test_infinity_modes_have_unscaled_bet_and_conditional_free(self):
  modes=self.modes('InfinityPull');self.assertEqual(len(modes),6)
  self.assertEqual({m['options']['game_mode'] for m in modes},{'low','medium','high'})
  self.assertTrue(all(m['options']['bet']==20 for m in modes))
  self.assertEqual({m['options']['game_mode']:m['cost_native'] for m in modes},{'low':20,'medium':40,'high':80})
 def test_chicken_payload_and_optionless_continuations(self):
  modes=self.modes('ChickenRush2');self.assertEqual(len(modes),8)
  self.assertTrue(all(set(m['options'])=={'bet','game_mode'} for m in modes))
  self.assertEqual(self.m.continuation_options(modes[0],'spin'),None)
  self.assertEqual(self.m.continuation_options(modes[0],'cashout'),None)
 def test_tile_three_risks_without_depth_explosion(self):
  modes=self.modes('TileMaster');self.assertEqual(len(modes),6)
  self.assertEqual({m['options']['risk_level'] for m in modes},{'low','medium','high'})
  self.assertTrue(all(m['command']=='start' and m['cost_native']==30 for m in modes))
  self.assertEqual(self.m.continuation_options(modes[0],'stop'),modes[0]['options'])
 def test_penalty_costs_and_variant_mode_restrictions(self):
  for gid in ['PenaltyDuel','PenaltyDuelWithJulioCesar']:
   modes=self.modes(gid)
   for mode in modes:
    if mode['command']=='bonus_buy':self.assertEqual(mode['options'],{'bet':10,'bonus':False});self.assertEqual(mode['cost_native'],1000)
    elif mode['options']['high_chance_buy']:self.assertEqual(mode['cost_native'],15)
    else:self.assertEqual(mode['cost_native'],10)
   if gid.endswith('Cesar'):self.assertEqual({x['options']['game_mode'] for x in modes if 'game_mode' in x['options']},{'striker'})
 def test_penalty_base_play_uses_only_source_button_sector_ids(self):
  for gid in ['PenaltyDuel','PenaltyDuelWithJulioCesar']:
   modes=[m for m in self.modes(gid) if m['command']=='play']
   self.assertTrue(all(type(m['options']['sector']) is int for m in modes))
   self.assertEqual({m['options']['sector'] for m in modes},set(range(1,11)))
 def test_audit_rejects_actual_julio_base_null_sector_shape(self):
  request={'command':'play','options':{'bet':10,'bonus':False,'game_mode':'striker','sector':None,'high_chance_buy':False}}
  r=report('PenaltyDuelWithJulioCesar',[(request,{'balance':99990,'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_fishing_sectors_and_original_multibets(self):
  modes=self.modes('FishingTime');single=[m for m in modes if len(m['options']['bets'])==1]
  self.assertEqual({next(iter(m['options']['bets'])) for m in single},{'white','grey','blue','yellow','red'})
  self.assertTrue(all(m['cost_native']==sum(m['options']['bets'].values()) for m in modes))
 def test_jogo_wire_has_no_invented_type_selector(self):
  modes=self.modes('JogoDoBicho');self.assertTrue(modes)
  for mode in modes:
   bet=mode['options']['bets'][0];self.assertNotIn('type',bet);self.assertEqual(bet['amount'],100)
  self.assertEqual({len(m['options']['bets'][0]['numbers']) for m in modes if 'numbers' in m['options']['bets'][0]},{2,3,4})
 def test_elements_cashout_requests_do_not_add_bet(self):
  modes=self.modes('ElementsOfPower');self.assertEqual(len(modes),2)
  self.assertEqual(modes[0]['options'],{'bet':10})
  for command in ['spin','cashout','partial_cashout','finish']:self.assertIsNone(self.m.continuation_options(modes[0],command))
 def test_native_held_money_not_counted_as_wallet_credit(self):
  check=self.m.wallet_check({'wallet':100000,'game':0},{'balance':{'wallet':99990,'game':11},'bets':{'initial':10,'win_amount':11},'game':{'state':'active'}},10,False)
  self.assertEqual(check['expected'],99990);self.assertEqual(check['held_native'],11)
  check=self.m.wallet_check({'wallet':99990,'game':11},{'balance':{'wallet':100001,'game':0},'bets':{'win_amount':11},'game':{'state':'closed'}},0,True)
  self.assertEqual(check['win_native'],11)
 def test_reject_wallet_discrepancy_and_floats(self):
  with self.assertRaises(ValueError):self.m.wallet_check(1000,{'balance':901,'bets':{'win_amount':0}},100,True)
  with self.assertRaises(ValueError):self.m.wallet_check(1000,{'balance':900.0,'bets':{'win_amount':0}},100,True)
 def test_chicken_paid_play_spin_cashout_only_once(self):
  i=initial('ChickenRush2');mode=next(m for m in self.modes('ChickenRush2') if m['target']=='spin')
  d=Demo(i,[{'balance':{'wallet':99990,'game':11},'bets':{'initial':10,'win_amount':11},'game':{'state':'active'},'available_commands':['spin','cashout']},
            {'balance':{'wallet':99990,'game':12},'bets':{'initial':10,'win_amount':12},'game':{'state':'active'},'available_commands':['spin','cashout']},
            {'balance':{'wallet':100002,'game':0},'bets':{'initial':10,'win_amount':12},'game':{'state':'closed'},'available_commands':['play']}])
  result=self.m.run(d,mode,i);self.assertEqual(result['status'],'closed')
  self.assertEqual([x[0] for x in d.requests],['play','spin','cashout']);self.assertEqual(d.requests[1][1],None)
 def test_lost_conditional_spin_is_pending(self):
  i=initial('ChickenRush2');mode=next(m for m in self.modes('ChickenRush2') if m['target']=='spin')
  d=Demo(i,[{'balance':{'wallet':99990,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'state':'closed'},'available_commands':['play']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'needs_trigger')
 def test_missing_wallet_check_payout_fails_and_retains_response(self):
  i=initial('InfinityPull');mode=self.modes('InfinityPull')[0]
  bad={'balance':99980,'game':{'state':'closed'},'available_commands':['play']};d=Demo(i,[bad])
  with self.assertRaises(ValueError):self.m.run(d,mode,i)
  self.assertIs(d.prev,bad)
 def test_elements_partial_needs_nonzero_source_proved_potential(self):
  self.assertFalse(self.m.elements_target_ready({'game':{'outcome':{'state':{'red':1,'green':0,'blue':0}},'partial_cashout_potential_multiplier':0}},'partial_cashout'))
  self.assertTrue(self.m.elements_target_ready({'game':{'outcome':{'state':{'red':2}},'partial_cashout_potential_multiplier':8}},'partial_cashout'))
 def test_jogo_native_returned_bet_wins_are_summed(self):
  check=self.m.wallet_check(1000,{'balance':1150,'bets':[{'amount':100,'win':300},{'amount':100,'win':50}]},200,True,'JogoDoBicho')
  self.assertEqual(check['win_native'],350)
 def test_partial_collection_credits_native_increment_only(self):
  check=self.m.wallet_check({'wallet':990,'game':40},{'balance':{'wallet':1005,'game':25},'bets':{'win_amount':15}},0,True)
  self.assertEqual(check['expected'],1005);self.assertEqual(check['held_native'],25)
 def test_infinity_freespin_is_unpaid_and_does_not_add_bonus_flag(self):
  i=initial('InfinityPull');mode=next(m for m in self.modes('InfinityPull') if m['target']=='freespin')
  d=Demo(i,[{'balance':99980,'bets':{'initial':20,'win_amount':0},'game':{'state':'freespin'},'available_commands':['freespin']},
            {'balance':100080,'bets':{'initial':0,'win_amount':100},'game':{'state':'closed'},'available_commands':['play']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'closed')
  self.assertEqual(d.requests[1],('freespin',mode['options']))
  self.assertEqual([c['cost_native'] for c in d.money_checks],[20,0])
 def test_closed_native_split_wallet_is_checked_without_rewriting_response(self):
  response={'balance':{'wallet':990,'game':15},'bets':{'win_amount':15},'game':{'state':'closed'}}
  check=self.m.wallet_check(1000,response,10,True)
  self.assertEqual(check['expected'],1005);self.assertEqual(check['actual'],1005)
  self.assertEqual(response['balance'],{'wallet':990,'game':15})
 def test_next_paid_attempt_uses_previous_closed_native_total(self):
  response={'balance':{'wallet':995,'game':0},'bets':{'win_amount':0},'game':{'state':'closed'}}
  check=self.m.wallet_check({'wallet':990,'game':15},response,10,True,before_closed=True)
  self.assertEqual(check['expected'],995)
 def test_null_jogo_loss_matches_source_truthy_win_sum(self):
  self.assertEqual(self.m.payout({'bets':[{'amount':100,'win':None}]},'JogoDoBicho'),0)
 def test_closed_game_credit_is_available_to_next_wager_precheck(self):
  i=initial('ChickenRush2');i['balance']={'wallet':0,'game':20};i['game']['state']='closed'
  mode=self.modes('ChickenRush2')[0]
  d=Demo(i,[{'balance':{'wallet':10,'game':0},'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']}])
  self.assertEqual(self.m.run(d,mode,i)['status'],'needs_trigger');self.assertEqual(len(d.requests),1)
 def test_infinity_returned_debit_must_match_multiplier(self):
  i=initial('InfinityPull');mode=next(m for m in self.modes('InfinityPull') if m['options']['game_mode']=='high')
  bad={'balance':99920,'bets':{'initial':20,'win_amount':0},'game':{'state':'closed'},'available_commands':['play']};d=Demo(i,[bad])
  with self.assertRaises(ValueError):self.m.run(d,mode,i)
  self.assertIs(d.prev,bad)
 def test_audit_original_init_reports_do_not_claim_gameplay(self):
  for gid in self.m.SUPPORTED:
   r=json.loads((ROOT/'live'/(gid+'.json')).read_text());r['events']=r['events'][:1];r['modes']=[]
   result=self.m.audit(r)
   self.assertEqual(result['failed'],0);self.assertEqual(result['paid_attempts'],0);self.assertEqual(result['rounds'],0)
 def test_audit_infinity_derives_multiplied_price_from_request(self):
  r=report('InfinityPull',[({'command':'play','options':{'bet':20,'bonus':False,'game_mode':'medium'}},
                          {'balance':99960,'bets':{'initial':40,'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  original=copy.deepcopy(r);result=self.m.audit(r)
  self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],40)
  self.assertEqual(result['paid_attempts'],1);self.assertEqual(r,original)
 def test_audit_penalty_ante_and_purchase_source_prices(self):
  for command,args,cost in [('play',{'bet':10,'bonus':False,'game_mode':'striker','sector':1,'high_chance_buy':True},15),
                            ('bonus_buy',{'bet':10,'bonus':False},1000)]:
   r=report('PenaltyDuel',[({'command':command,'options':args}, {'balance':{'wallet':100000-cost,'game':0},'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play','bonus_buy']})])
   result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],cost)
 def test_audit_fishing_and_jogo_sum_native_request_components(self):
  fishing=report('FishingTime',[({'command':'play','options':{'bets':{'white':20,'red':10}}},
                               {'balance':{'wallet':99970,'game':0},'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(fishing);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],30)
  bets=[{'amount':100,'animals':['ostrich']},{'amount':200,'numbers':['0','1']}]
  jogo=report('JogoDoBicho',[({'command':'play','options':{'bets':bets}},
                           {'balance':99700,'bets':[dict(x,win=None) for x in bets],'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(jogo);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],300)
 def test_audit_does_not_charge_stale_initial_on_unpaid_spin(self):
  q={'command':'play','options':{'bet':10,'game_mode':'easy'}}
  r=report('ChickenRush2',[(q,{'balance':{'wallet':99990,'game':11},'bets':{'initial':10,'win_amount':11},'game':{'state':'active'},'available_commands':['spin','cashout']}),
      ({'command':'spin'},{'balance':{'wallet':99990,'game':12},'bets':{'initial':10,'win_amount':12},'game':{'state':'active'},'available_commands':['cashout']}),
      ({'command':'cashout'},{'balance':{'wallet':100002,'game':0},'bets':{'initial':10,'win_amount':12},'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],10);self.assertEqual(result['rounds'],1)
 def test_audit_closed_held_credit_is_used_by_next_paid_request(self):
  q={'command':'play','options':{'bet':10,'game_mode':'easy'}}
  r=report('ChickenRush2',[(q,{'balance':{'wallet':99990,'game':15},'bets':{'win_amount':15},'game':{'state':'closed'},'available_commands':['play']}),
                         (q,{'balance':{'wallet':99995,'game':0},'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],20);self.assertEqual(result['rounds'],2)
 def test_audit_rejects_forged_ante_cost_even_if_runner_claims_success(self):
  r=report('PenaltyDuel',[({'command':'play','options':{'bet':10,'bonus':False,'game_mode':'striker','sector':1,'high_chance_buy':True}},
      {'balance':99990,'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_audit_rejects_hidden_bet_on_optionless_cashout(self):
  r=report('ChickenRush2',[({'command':'play','options':{'bet':10,'game_mode':'easy'}},
      {'balance':99990,'bets':{'win_amount':0},'game':{'state':'active'},'available_commands':['cashout']}),
      ({'command':'cashout','options':{'bet':10}},{'balance':99990,'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_audit_rejects_second_paid_action_inside_pending_round(self):
  q={'command':'play','options':{'bet':10,'game_mode':'easy'}}
  r=report('ChickenRush2',[(q,{'balance':99990,'bets':{'win_amount':0},'game':{'state':'active'},'available_commands':['play']}),
                         (q,{'balance':99980,'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_audit_init_only_cannot_support_a_closed_mode_claim(self):
  r=report('ChickenRush2',[]);r['modes']=[{'status':'closed','first_event':0,'last_event':0}]
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_audit_tile_stop_payload_bet_is_not_a_second_debit(self):
  args={'bet':30,'bonus':False,'risk_level':'low'}
  r=report('TileMaster',[({'command':'start','options':args},{'balance':99970,'bets':{'initial':30,'win_amount':33},'game':{'state':'alive'},'available_commands':['spin','stop']}),
      ({'command':'spin','options':args},{'balance':99970,'bets':{'initial':30,'win_amount':45},'game':{'state':'alive'},'available_commands':['stop']}),
      ({'command':'stop','options':args},{'balance':100015,'bets':{'initial':30,'win_amount':45},'game':{'state':'closed'},'available_commands':['start']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],30)
 def test_audit_penalty_bonus_play_is_unpaid(self):
  r=report('PenaltyDuel',[({'command':'bonus_buy','options':{'bet':10,'bonus':False}},
      {'balance':{'wallet':99000,'game':0},'bets':{'initial':1000,'win_amount':0},'game':{'state':'bonus_state'},'available_commands':['bonus_play']}),
      ({'command':'bonus_play','options':{'bet':10,'bonus':False,'game_mode':'striker','sector':None,'high_chance_buy':False}},
      {'balance':{'wallet':101000,'game':0},'bets':{'initial':1000,'win_amount':2000},'game':{'state':'closed'},'available_commands':['play','bonus_buy']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],1000)
 def test_audit_elements_partial_and_full_collection_native_increments(self):
  r=report('ElementsOfPower',[({'command':'play','options':{'bet':10}},
      {'balance':{'wallet':99990,'game':40},'bets':{'win_amount':40},'game':{'state':'active','partial_cashout_potential_multiplier':15,'outcome':{'state':{'blue':2}}},'available_commands':['partial_cashout','cashout','spin']}),
      ({'command':'partial_cashout'},{'balance':{'wallet':100005,'game':25},'bets':{'win_amount':15},'game':{'state':'active','outcome':{'state':{'blue':1}}},'available_commands':['cashout']}),
      ({'command':'cashout'},{'balance':{'wallet':100030,'game':0},'bets':{'win_amount':25},'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],10)
 def test_audit_infinity_triggered_freespin_is_unpaid(self):
  args={'bet':20,'bonus':False,'game_mode':'low'}
  r=report('InfinityPull',[({'command':'play','options':args},{'balance':99980,'bets':{'initial':20,'win_amount':0},'game':{'state':'freespin'},'available_commands':['freespin']}),
      ({'command':'freespin','options':args},{'balance':100080,'bets':{'initial':0,'win_amount':100},'game':{'state':'closed'},'available_commands':['play']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],20)
 def test_audit_rejects_conditional_mode_claim_when_action_never_fired(self):
  q={'command':'play','options':{'bet':10,'game_mode':'easy'}}
  r=report('ChickenRush2',[(q,{'balance':99990,'bets':{'win_amount':0},'game':{'state':'closed'},'available_commands':['play']})])
  mode=next(m for m in self.modes('ChickenRush2') if m['target']=='spin')
  r['modes']=[{'mode':mode,'status':'closed','first_event':1,'last_event':1}]
  self.assertGreater(self.m.audit(r)['failed'],0)
 def test_elements_finished_cashout_retains_award_until_finish(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0]
  first={'balance':{'wallet':99990,'game':0},'bets':{'win_amount':0},'game':{'state':'active','outcome':{'state':{'green':1}}},'available_commands':['cashout','spin']}
  cash={'balance':{'wallet':99990,'game':25},'bets':{'win_amount':25},'game':{'state':'finished','action':'cashout'},'available_commands':['init','finish']}
  done={'balance':{'wallet':100015,'game':0},'game':{'state':'closed','action':'finish'},'available_commands':['init','play']}
  d=Demo(i,[first,cash,done]);result=self.m.run(d,mode,i)
  self.assertEqual(result['status'],'closed');self.assertEqual([c['win_native'] for c in d.money_checks],[0,0,25])
  self.assertEqual(d.money_checks[-1]['released_held_native'],25);self.assertEqual(cash['balance'],{'wallet':99990,'game':25})
  audited=self.m.audit(report('ElementsOfPower',i and [({'command':'play','options':mode['options']},first),({'command':'cashout'},cash),({'command':'finish'},done)]))
  self.assertEqual(audited['failed'],0)
 def test_resume_received_elements_finishes_once_without_repeating_cashout(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0]
  first={'balance':{'wallet':99990,'game':0},'bets':{'win_amount':0},'game':{'state':'active','outcome':{'state':{'green':1}}},'available_commands':['cashout','spin']}
  cash={'balance':{'wallet':99990,'game':25},'bets':{'win_amount':25},'game':{'state':'finished','action':'cashout'},'available_commands':['init','finish']}
  done={'balance':{'wallet':100015,'game':0},'game':{'state':'closed','action':'finish'},'available_commands':['init','play']}
  d=Demo(cash,[done]);d.events=report('ElementsOfPower',[({'command':'play','options':mode['options']},first),({'command':'cashout'},cash)])['events'];d.last_response=cash
  result=self.m.resume_received(d,mode,i)
  self.assertEqual(d.requests,[('finish',None)]);self.assertEqual(result['first_event'],1);self.assertEqual(result['last_event'],3)
  self.assertEqual(result['status'],'closed');self.assertEqual(result['final_balance'],done['balance'])
 def test_resume_received_refuses_unfinished_or_repeat_ready_state(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0];d=Demo(i,[])
  with self.assertRaises(ValueError):self.m.resume_received(d,mode,i)
  self.assertEqual(d.requests,[])
 def test_infinity_closed_init_only_refresh_is_separate_from_gameplay_win(self):
  i=initial('InfinityPull');mode=self.modes('InfinityPull')[0]
  old={'balance':99980,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  fresh=copy.deepcopy(i);fresh['balance']=100000
  done={'balance':99980,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  d=Demo(old,[fresh,done]);result=self.m.run(d,mode,i)
  self.assertEqual(result['status'],'closed');self.assertEqual(d.requests[0],('init',None));self.assertEqual(d.requests[1][0],'play')
  refresh=next(c for c in d.money_checks if c['kind']=='native_fun_balance_refresh')
  self.assertEqual(refresh['before_native'],99980);self.assertEqual(refresh['after_native'],100000);self.assertTrue(refresh['not_gameplay'])
  self.assertEqual(d.money_checks[-1]['win_native'],0)
 def test_infinity_resume_remaining_does_not_replay_received_play(self):
  i=initial('InfinityPull');mode=self.modes('InfinityPull')[0]
  old={'balance':99980,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  fresh=copy.deepcopy(i);fresh['balance']=99980
  done={'balance':99960,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  d=Demo(old,[fresh,done]);d.last_response=old
  results=list(self.m.resume_remaining(d,[mode],i))
  self.assertEqual(len(results),1);self.assertEqual([x[0] for x in d.requests],['init','play'])
 def test_resume_remaining_yields_before_next_paid_mode_for_parent_checkpoint(self):
  i=initial('InfinityPull');mode=self.modes('InfinityPull')[0]
  old={'balance':99980,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  fresh=copy.deepcopy(i);fresh['balance']=99980
  done={'balance':99960,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  fresh2=copy.deepcopy(i);fresh2['balance']=99960
  done2={'balance':99940,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}
  d=Demo(old,[fresh,done,fresh2,done2]);d.last_response=old
  iterator=iter(self.m.resume_remaining(d,[mode,mode],i));self.assertEqual(next(iterator)['status'],'closed')
  self.assertEqual(len(d.requests),2)
 def test_audit_records_infinity_fun_refresh_without_calling_it_win(self):
  i=initial('InfinityPull');fresh=copy.deepcopy(i)
  r=report('InfinityPull',[({'command':'play','options':{'bet':20,'bonus':False,'game_mode':'low'}},
       {'balance':99980,'bets':{'initial':20.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']}),
       ({'command':'init'},fresh),
       ({'command':'play','options':{'bet':20,'bonus':False,'game_mode':'medium'}},
       {'balance':99960,'bets':{'initial':40.0,'win_amount':0},'game':{'state':'closed'},'available_commands':['init']})])
  result=self.m.audit(r);self.assertEqual(result['failed'],0);self.assertEqual(result['cost_native'],60)
  self.assertTrue(any(c['kind']=='native_fun_balance_refresh' and c['not_gameplay'] for c in result['checks']))
 def test_elements_resume_after_explicit_received_init_uses_actual_fresh_wallet(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0]
  first={'balance':{'wallet':99990,'game':0},'bets':{'win_amount':0},'game':{'state':'active','outcome':{'state':{'green':1}}},'available_commands':['cashout','spin']}
  cash={'balance':{'wallet':99990,'game':25},'bets':{'initial':10,'win_amount':25},'game':{'state':'finished','action':'cashout','outcome':{'state':{'green':0}}},'available_commands':['init','finish']}
  fresh=copy.deepcopy(cash);fresh['balance']['wallet']=100000;fresh['options']=copy.deepcopy(i['options']);fresh['game']['action']='init'
  done={'balance':{'wallet':100025,'game':0},'game':{'state':'closed','action':'finish'},'available_commands':['init','play']}
  r=report('ElementsOfPower',[({'command':'play','options':mode['options']},first),({'command':'cashout'},cash),({'command':'init'},fresh)])
  d=Demo(fresh,[done]);d.events=r['events'];d.last_response=fresh
  result=self.m.resume_received(d,mode,i)
  self.assertEqual(d.requests,[('finish',None)]);self.assertEqual(result['final_balance']['wallet'],100025)
  self.assertTrue(any(c['kind']=='native_fun_balance_refresh' and c['delta_native']==10 for c in d.money_checks))
  full=report('ElementsOfPower',[({'command':'play','options':mode['options']},first),({'command':'cashout'},cash),({'command':'init'},fresh),({'command':'finish'},done)])
  self.assertEqual(self.m.audit(full)['failed'],0)
 def test_actual_elements_init_action_echo_keeps_same_pending_cashout(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0]
  first={'balance':{'wallet':99990,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'play','state':'active','game_mode':'default','outcome':{'state':{'blue':0,'green':1,'red':0},'game_win':25,'instant_win':0,'symbol':'green','instant_win_columns':[]}},'available_commands':['init','spin','cashout']}
  cash={'balance':{'wallet':99990,'game':25},'bets':{'initial':10,'win_amount':25},'game':{'action':'cashout','state':'finished','game_mode':'default','outcome':{'state':{'blue':0,'green':0,'red':0},'game_win':0,'instant_win':25}},'available_commands':['init','finish']}
  read=copy.deepcopy(cash);read['game']['action']='init';read['options']=copy.deepcopy(i['options'])
  done={'balance':{'wallet':100015,'game':0},'game':{'action':'finish','state':'closed'},'available_commands':['init','play']}
  d=Demo(read,[done]);d.last_response=read;d.events=report('ElementsOfPower',[({'command':'play','options':mode['options']},first),({'command':'cashout'},cash),({'command':'init'},read)])['events']
  self.assertEqual(self.m.resume_received(d,mode,i)['status'],'closed');self.assertEqual(d.requests,[('finish',None)])
 def test_elements_init_refresh_cannot_change_held_prize_or_pending_identity(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[0]
  first={'balance':{'wallet':99990,'game':0},'game':{'state':'active'},'available_commands':['cashout']}
  cash={'balance':{'wallet':99990,'game':25},'bets':{'win_amount':25},'game':{'state':'finished','action':'cashout'},'flow':{'round_id':'own-round'},'available_commands':['init','finish']}
  for field in ('game','identity'):
   fresh=copy.deepcopy(cash);fresh['options']=copy.deepcopy(i['options'])
   if field=='game':fresh['balance']['game']=26
   else:fresh['flow']['round_id']='different-round'
   d=Demo(fresh,[]);d.last_response=fresh;d.events=report('ElementsOfPower',[({'command':'play','options':mode['options']},first),({'command':'cashout'},cash),({'command':'init'},fresh)])['events']
   with self.assertRaises(ValueError):self.m.resume_received(d,mode,i)
   self.assertEqual(d.requests,[])
 def test_elements_optionless_spin_pays_retained_base_bet(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[1]
  a={'balance':{'wallet':99990,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'play','state':'active','outcome':{'state':{'green':1}}},'available_commands':['spin','cashout']}
  b={'balance':{'wallet':99980,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'spin','state':'active','partial_cashout_potential_multiplier':1,'outcome':{'state':{'green':2}}},'available_commands':['spin','cashout','partial_cashout']}
  c={'balance':{'wallet':99980,'game':25},'bets':{'initial':10,'win_amount':25},'game':{'action':'partial_cashout','state':'finished'},'available_commands':['finish']}
  end={'balance':{'wallet':100005,'game':0},'game':{'action':'finish','state':'closed'},'available_commands':['play']}
  d=Demo(i,[a,b,c,end]);result=self.m.run(d,mode,i)
  self.assertEqual(result['status'],'closed');self.assertEqual([x['cost_native'] for x in d.money_checks],[10,10,0,0])
  self.assertEqual(d.requests[1],('spin',None));self.assertEqual(mode['continuation_cost_native'],10)
  r=report('ElementsOfPower',[({'command':'play','options':mode['options']},a),({'command':'spin'},b),({'command':'partial_cashout'},c),({'command':'finish'},end)])
  audited=self.m.audit(r);self.assertEqual(audited['failed'],0);self.assertEqual(audited['cost_native'],20);self.assertEqual(audited['paid_attempts'],1)
 def test_resume_received_active_spin_does_not_resend_it(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[1]
  a={'balance':{'wallet':100005,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'play','state':'active','outcome':{'state':{'blue':1}}},'available_commands':['init','spin','cashout']}
  b={'balance':{'wallet':99995,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'spin','state':'active','partial_cashout_potential_multiplier':1,'outcome':{'state':{'blue':1,'green':1}}},'available_commands':['init','spin','cashout','partial_cashout']}
  c={'balance':{'wallet':99995,'game':41},'bets':{'initial':10,'win_amount':41},'game':{'action':'partial_cashout','state':'finished'},'available_commands':['finish']}
  end={'balance':{'wallet':100036,'game':0},'game':{'action':'finish','state':'closed'},'available_commands':['play']}
  d=Demo(b,[c,end]);d.last_response=b;d.events=report('ElementsOfPower',[({'command':'play','options':mode['options']},a),({'command':'spin'},b)])['events']
  result=self.m.resume_received_spin(d,mode,i)
  self.assertEqual(result['status'],'closed');self.assertEqual([x[0] for x in d.requests],['partial_cashout','finish'])
  normalized=next(c for c in d.money_checks if c.get('normalized_received_spin'))
  self.assertEqual(normalized['cost_native'],10);self.assertEqual(normalized['expected'],99995)
 def test_elements_paid_spin_budget_closes_without_faking_partial_target(self):
  i=initial('ElementsOfPower');mode=self.modes('ElementsOfPower')[1];mode['max_additional_paid_spins']=0
  a={'balance':{'wallet':99990,'game':0},'bets':{'initial':10,'win_amount':0},'game':{'action':'play','state':'active','outcome':{'state':{'green':1}}},'available_commands':['spin','cashout']}
  c={'balance':{'wallet':99990,'game':25},'bets':{'initial':10,'win_amount':25},'game':{'action':'cashout','state':'finished'},'available_commands':['finish']}
  end={'balance':{'wallet':100015,'game':0},'game':{'action':'finish','state':'closed'},'available_commands':['play']}
  d=Demo(i,[a,c,end]);result=self.m.run(d,mode,i)
  self.assertEqual(result['status'],'needs_trigger');self.assertEqual([x[0] for x in d.requests],['play','cashout','finish'])
 def test_elements_partial_eligibility_uses_source_progress_paytable_when_api_field_absent(self):
  i=initial('ElementsOfPower')
  response={'game':{'state':'active','outcome':{'state':{'blue':0,'green':2,'red':0}}},'available_commands':['partial_cashout']}
  self.assertTrue(self.m.elements_target_ready(response,'partial_cashout',i))
  response['game']['outcome']['state']['green']=1
  self.assertFalse(self.m.elements_target_ready(response,'partial_cashout',i))

class Demo:
 def __init__(self,i,responses):self.prev=i;self.responses=iter(responses);self.events=[];self.requests=[];self.money_checks=[]
 def call(self,command,options=None):
  self.requests.append((command,options));response=next(self.responses);self.events.append({'response':response});return response

if __name__=='__main__':unittest.main()
