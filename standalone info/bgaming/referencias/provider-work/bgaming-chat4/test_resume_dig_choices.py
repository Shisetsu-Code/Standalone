import copy,importlib.util,json,unittest
from pathlib import Path
from types import SimpleNamespace
from run_demo_qa import Demo
from bonus_choices_extra import metadata
if importlib.util.find_spec('resume_dig_choices'):
 import resume_dig_choices as helper
else:helper=None
ROOT=Path(__file__).resolve().parent;PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def proof():return metadata('DigDigDigger',next((PRIVATE/'research/legacy/DigDigDigger').rglob('bundle.js')).read_text(encoding='utf8'))
def fixture():
 archive=ROOT/'live/attempts/DigDigDigger.before-dig-choice-recovery.json';r=json.loads((archive if archive.exists() else ROOT/'live/DigDigDigger.json').read_text(encoding='utf8'));r['events']=r['events'][:2];r['modes']=[];r['declared_modes']=r['declared_modes'][:1];r['checks']=r['checks'][:1]
 return r
class FakeDemo:
 run_mode=Demo.run_mode
 settle=Demo.settle
 continuation_options=Demo.continuation_options
 def __init__(self,r,win=False,bonus=False,bad=False,uncertain=False):
  self.game={'game_id':'DigDigDigger'};self.events=r['events'];self.money_checks=r['checks'];self.last_response=copy.deepcopy(self.events[-1]['response']);self.prev=None;self.series='round_series_id-1';self.clean=SimpleNamespace(clean=lambda x:copy.deepcopy(x));self.protocol_metadata=r['protocol_metadata'];self.calls=[];self.win=win;self.bonus=bonus;self.bad=bad;self.uncertain=uncertain
 def call(self,command,options=None):
  self.calls.append((command,copy.deepcopy(options)))
  if self.uncertain:
   self.events.append({'request':{'command':command},'status':'uncertain'});raise RuntimeError('Synthetic uncertain request; no retry')
  before=self.last_response;r=copy.deepcopy(before);r.pop('gamble',None);r['flow']['command']=command;r['flow']['last_action_id']='next-'+str(len(self.calls))
  r.pop('options',None)
  if command=='gamble':
   amount=before['balance']['game']*(2 if options['bet'] in ('black','red') else 4) if self.win else 0;r['balance']['game']=amount;r['gamble']={'win':self.win,'value':'000s'};r['flow'].update(state='gamble' if self.win else 'closed',available_actions=['init','gamble','close'] if self.win else ['init','spin'])
   if self.bad:r['balance']['wallet']+=1
  elif command=='close':r['flow'].update(state='closed',available_actions=['init','spin'])
  elif command=='spin':
   r['balance']={'wallet':before['balance']['wallet']+before['balance']['game']-self.active_mode['cost_native'],'game':0};r['outcome']={'bet':options['bet'],'win':0};feature=options.get('purchased_feature');r['flow']['purchased_feature']={'name':feature} if feature else {};r['flow'].update(state='freespins' if feature else 'closed',available_actions=['init','freespin'] if feature else ['init','spin'])
  elif command=='freespin':r['balance']['game']=10;r['flow'].update(state='gamble',available_actions=['init','gamble','close'])
  else:raise AssertionError(command)
  self.last_response=r;q={'command':command,'extra_data':{'round_series_id':self.series}}
  if options is not None:q['options']=copy.deepcopy(options)
  self.events.append({'request':q,'response':copy.deepcopy(r),'status':200,'time':'synthetic-'+str(len(self.calls))});return r
 def credentials(self):return {'fresh_demo':True,'game_id':'DigDigDigger','operation':{'status':'received'},'last_response':copy.deepcopy(self.last_response),'series':self.series}
class DigRecovery(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(helper,'Guarded Dig recovery helper required')
 def test_original_paid_round_all_six_choices_then_close_no_spin(self):
  r=fixture();d=FakeDemo(r,win=True);saved=[];helper.execute(d,r,d.credentials(),proof(),persist=lambda:saved.append(len(d.events)))
  self.assertEqual([x[0] for x in d.calls],['gamble']*6+['close']);self.assertEqual([x[1]['bet'] for x in d.calls[:6]],['s','c','d','h','black','red']);self.assertEqual(r['status'],'complete_declared_modes');self.assertTrue(r['modes'][0]['resumed_existing_round']);self.assertEqual(r['modes'][0]['first_event'],1);self.assertTrue(r['bonus_mode_coverage']['collect_tested']);self.assertTrue(all(c['ok'] for c in r['checks']));self.assertTrue(saved)
 def test_loss_closes_original_round_without_rebuy_or_collect(self):
  r=fixture();d=FakeDemo(r);helper.execute(d,r,d.credentials(),proof())
  self.assertEqual(d.calls,[('gamble',{'bet':'s'})]);self.assertEqual(r['modes'][0]['final_state'],'closed');self.assertEqual(r['status'],'partial');self.assertEqual(r['bonus_mode_coverage']['tested'],['s'])
 def test_other_bonus_states_use_existing_settle_then_intercept_received_gamble(self):
  r=fixture();r['declared_modes'].append({'name':'freespin_buy','command':'spin','options':{'bet':10,'purchased_feature':'freespin_buy'},'cost_native':100});d=FakeDemo(r)
  helper.execute(d,r,d.credentials(),proof());self.assertEqual([x[0] for x in d.calls],['gamble','spin','freespin','gamble']);self.assertEqual(d.calls[-1],('gamble',{'bet':'c'}));self.assertEqual(len(r['modes']),2);self.assertTrue(all(m['final_state']=='closed' for m in r['modes']));self.assertTrue(any(c.get('kind')=='dig_native_continuation_wallet' for c in r['checks']))
 def test_optional_cards_each_one_paid_attempt_and_no_hidden_trigger_retry(self):
  r=fixture();d=FakeDemo(r);helper.execute(d,r,d.credentials(),proof(),include_conditional=True)
  self.assertEqual(sum(c[0]=='spin' for c in d.calls),6);conditional=[m for m in r['modes'] if m['mode'].get('conditional_card')];self.assertEqual(len(conditional),6);self.assertTrue(all(m['status']=='needs_trigger' and m['round_status']=='closed' and m['attempted_once'] for m in conditional));self.assertEqual(r['status'],'partial')
 def test_native_mismatch_preserves_failed_check_and_stops_before_another_action(self):
  r=fixture();d=FakeDemo(r,bad=True);helper.execute(d,r,d.credentials(),proof());self.assertEqual(len(d.calls),1);self.assertEqual(r['status'],'needs_review');self.assertTrue(any(c.get('ok') is False for c in r['checks']));self.assertEqual(len(r['events']),3)
 def test_uncertain_action_stops_without_replay(self):
  r=fixture();d=FakeDemo(r,uncertain=True);helper.execute(d,r,d.credentials(),proof());self.assertEqual(len(d.calls),1);self.assertEqual(r['status'],'needs_review');self.assertEqual(r['events'][-1]['status'],'uncertain')
 def test_bad_ownership_or_checkpoint_blocks_before_sending(self):
  for change in ['fresh','checkpoint','currency']:
   r=fixture();d=FakeDemo(r);c=d.credentials()
   if change=='fresh':c['fresh_demo']=False
   if change=='checkpoint':c['last_response']['balance']['wallet']+=1
   if change=='currency':r['events'][0]['response']['options']['currency']['code']='EUR'
   with self.assertRaises(ValueError):helper.execute(d,r,c,proof())
   self.assertFalse(d.calls)
 def test_active_running_or_continue_gate_blocks_and_native_pacing_is_bounded(self):
  with self.assertRaises(RuntimeError):helper.require_paused({'active_game':'another'},'PAUSE')
  with self.assertRaises(RuntimeError):helper.require_paused({'active_game':None},'CONTINUE')
  helper.require_paused({'active_game':None},'PAUSE');self.assertEqual(helper.pacing_delay({'last_launch_epoch':100},130),30);self.assertEqual(helper.pacing_delay({'last_launch_epoch':100},200),0)
if __name__=='__main__':unittest.main()
