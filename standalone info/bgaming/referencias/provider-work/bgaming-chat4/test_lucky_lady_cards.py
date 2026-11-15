"""Offline finite slot-card choices; no live session or provider requests."""
import copy
import importlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent


def old_report():
 archive=ROOT/'live/attempts/LuckyLadyClover.before-finite-cards.json'
 return json.loads((archive if archive.exists() else ROOT/'live/LuckyLadyClover.json').read_text())


def initial():
 return {'options':{'line_bets':[10,25],'lines':[[0]*5 for _ in range(9)],'currency':{'code':'FUN','subunits':100}},
         'balance':100000,'game':{'state':'idle'},'available_commands':['init','spin']}


class LuckyLadyCardsTests(unittest.TestCase):
 def setUp(self):
  self.m=importlib.import_module('run_lucky_lady_cards');self.slot,self.proof=self.m.cached_proofs()
 def test_six_semantic_choices_are_finite_and_minimum_spin_is_native(self):
  plan=self.m.declared_choices(initial(),self.slot,self.proof)
  self.assertEqual([m['options']['bet'] for m in plan],['s','c','d','h','black','red'])
  self.assertTrue(all(m['trigger_mode']['cost_native']==90 for m in plan))
  self.assertTrue(all(set(m['options'])=={'bet'} for m in plan))
 def test_each_choice_executes_once_even_when_every_gamble_loses(self):
  d=Fake('lose');context=self.m.run_choices(d,initial(),self.slot,self.proof)
  self.assertEqual([q['options']['bet'] for q in d.requests if q['command']=='check_card'],['s','c','d','h','black','red'])
  self.assertEqual(len(context['modes']),6);self.assertEqual(context['gross_native_debit'],1440)
  audit=self.m.audit_context(context,self.proof);self.assertEqual(audit['failed'],0);self.assertTrue(audit['complete'])
 def test_win_collects_immediately_without_repeated_gamble_levels(self):
  d=Fake('win');context=self.m.run_choices(d,initial(),self.slot,self.proof,max_attempts=1,gross_native_budget=9000)
  self.assertEqual([q['command'] for q in d.requests],['spin','check_card','finish'])
  self.assertEqual(context['modes'][0]['mode']['options']['bet'],'s');self.assertEqual(context['modes'][0]['final_balance'],100510)
  self.assertFalse(self.m.audit_context(context,self.proof)['complete'])
 def test_hard_attempt_and_native_budget_caps_stop_without_more_spins(self):
  d=Fake('no_trigger');context=self.m.run_choices(d,initial(),self.slot,self.proof)
  self.assertEqual(len(d.requests),100);self.assertEqual(context['gross_native_debit'],9000)
  self.assertEqual(context['modes'],[]);self.assertEqual(len(self.m.audit_context(context,self.proof)['pending_choices']),6)
  d=Fake('lose')
  with self.assertRaises(ValueError):self.m.run_choices(d,initial(),self.slot,self.proof,max_attempts=101)
  self.assertEqual(d.requests,[])
 def test_over_budget_gamble_is_collected_and_does_not_count_as_choice(self):
  d=Fake('lose');context=self.m.run_choices(d,initial(),self.slot,self.proof,gross_native_budget=180)
  self.assertEqual([q['command'] for q in d.requests],['spin','finish','spin','finish'])
  self.assertEqual(context['gross_native_debit'],180);self.assertEqual(context['modes'],[])
 def test_native_audit_rejects_balance_tamper_and_second_gamble_level(self):
  d=Fake('win');context=self.m.run_choices(d,initial(),self.slot,self.proof,max_attempts=1)
  tampered=copy.deepcopy(context);tampered['events'][2]['response']['balance']+=1
  self.assertGreater(self.m.audit_context(tampered,self.proof)['failed'],0)
  repeated=copy.deepcopy(context);repeated['events'].insert(3,copy.deepcopy(repeated['events'][2]))
  self.assertGreater(self.m.audit_context(repeated,self.proof)['failed'],0)
 def test_original_normal_finish_are_preserved_with_scoped_context_modes(self):
  old=old_report();saved=copy.deepcopy(old);d=Fake('lose');context=self.m.run_choices(d,initial(),self.slot,self.proof)
  combined=self.m.derive_report(old,context,self.proof)
  self.assertEqual(combined['contexts'][0]['report'],old);self.assertEqual(old,saved)
  self.assertNotIn('events',combined);self.assertEqual(len(combined['modes']),7);self.assertEqual(len(combined['declared_modes']),7)
  self.assertEqual(combined['status'],'complete_declared_modes')
 def test_context_path_does_not_add_a_second_flat_live_json(self):
  context,canonical=self.m.output_paths(ROOT)
  self.assertEqual(context,ROOT/'live/bonus-contexts/LuckyLadyClover.finite-cards.context.json')
  self.assertEqual(canonical,ROOT/'live/LuckyLadyClover.json')


class Fake:
 def __init__(self,outcome):
  self.outcome=outcome;self.current=initial();self.requests=[];self.money_checks=[];self.prev=self.current
  self.events=[{'request':{'command':'init'},'response':copy.deepcopy(self.current),'status':200}]
 def call(self,command,options=None):
  q={'command':command}
  if options is not None:q['options']=copy.deepcopy(options)
  self.requests.append(q);old=self.current
  if command=='spin':
   if self.outcome=='no_trigger':r={'balance':old['balance']-90,'game':{'state':'closed'},'available_commands':['init','spin']}
   else:r={'balance':old['balance']-90+150,'result':{'total':150},'bets':{'required_for_bonus_game':150},'game':{'state':'check_card'},'available_commands':['init','check_card','finish']}
  elif command=='check_card':
   choice=options['bet'];stake=old['bets']['required_for_bonus_game'];win=self.outcome=='win';payout=stake*(2 if choice in ('black','red') else 4) if win else 0
   r={'balance':old['balance']-stake+payout,'bets':{'bonus_game':stake},'game':{'state':'check_card' if win else 'closed','bonus_game':{'result':'win' if win else 'lose','card':'A_S','bet':choice}},'available_commands':['init','check_card','finish'] if win else ['init','spin']}
   if win:r['result']={'total':payout,'bonus_game':payout};r['bets']['required_for_bonus_game']=payout
  elif command=='finish':r={'balance':old['balance'],'game':{'state':'closed'},'available_commands':['init','spin']}
  else:raise AssertionError('Unproved fake input')
  self.current=r;self.last_response=r;self.events.append({'request':q,'response':copy.deepcopy(r),'status':200});return r

if __name__=='__main__':unittest.main()
