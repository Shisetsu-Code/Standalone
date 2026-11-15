import copy,importlib.util,json,unittest
from pathlib import Path
from test_resume_dig_choices import FakeDemo,proof
if importlib.util.find_spec('resume_dig_received_closed'):
 import resume_dig_received_closed as helper
else:helper=None
ROOT=Path(__file__).resolve().parent
def received():
 archive=ROOT/'live/attempts/DigDigDigger.before-received-dig-loss-classification.json';r=json.loads((archive if archive.exists() else ROOT/'live/DigDigDigger.json').read_text(encoding='utf8'));r['events']=r['events'][:3];r['modes']=[];r['declared_modes']=r['declared_modes'][:2];r['checks']=[{'expected':99990,'actual':99990,'ok':True},{'kind':'dig_native_check_failure','event':2,'command':'gamble','ok':False,'error_type':'ValueError'}];r.pop('dig_received_loss_classified',None);r.pop('remaining_baseline_observation',None);return r
class ReceivedDemo(FakeDemo):
 def call(self,command,options=None):
  if command!='init':return super().call(command,options)
  self.calls.append(('init',None));r=copy.deepcopy(self.events[0]['response']);r['balance']={'wallet':100000,'game':0};r['flow']=dict(self.last_response['flow'],state='closed',available_actions=['init','spin']);self.last_response=r;self.events.append({'request':{'command':'init'},'response':copy.deepcopy(r),'status':200,'time':'synthetic-init'});return r
class DigReceived(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(helper,'Exact received loss classification helper required')
 def test_received_closed_outcome_classifies_without_rewriting_events_or_failed_checks(self):
  r=received();events=copy.deepcopy(r['events']);checks=copy.deepcopy(r['checks']);helper.classify_received(r,proof());self.assertEqual(r['events'],events);self.assertEqual(r['checks'][:2],checks);self.assertEqual(r['modes'][0]['status'],'closed_financial_anomaly');self.assertEqual(r['modes'][0]['gamble_choices_executed'],['s']);self.assertEqual(r['status'],'needs_review');self.assertEqual(r['checks'][-1]['wallet_delta_native'],10);self.assertFalse(r['checks'][-1]['ok'])
 def test_wrong_received_event_or_repeated_classification_blocks_offline(self):
  r=received();r['events'][2]['response']['gamble']['win']=1
  with self.assertRaises(ValueError):helper.classify_received(r,proof())
  r=received();helper.classify_received(r,proof())
  with self.assertRaises(ValueError):helper.classify_received(r,proof())
 def test_explicit_fresh_init_is_separate_baseline_then_only_unplayed_mode_and_close(self):
  r=received();d=ReceivedDemo(r);helper.classify_received(r,proof());helper.continue_unplayed(d,r,d.credentials(),proof());self.assertEqual([c[0] for c in d.calls],['init','spin','freespin','close']);self.assertFalse(any(c[0]=='gamble' for c in d.calls));self.assertEqual(r['remaining_baseline_observation']['before_native'],{'game':0,'wallet':100000});self.assertEqual(r['remaining_declared_modes_status'],'complete');self.assertEqual(r['status'],'needs_review');self.assertEqual(r['modes'][0]['financial_status'],'failed');self.assertTrue(any(c.get('ok') is False for c in r['checks']))
 def test_unowned_checkpoint_cannot_send_new_init(self):
  r=received();d=ReceivedDemo(r);helper.classify_received(r,proof());c=d.credentials();c['fresh_demo']=False
  with self.assertRaises(ValueError):helper.continue_unplayed(d,r,c,proof())
  self.assertFalse(d.calls)
 def test_received_wallet_anomaly_is_not_removed_by_same_balance_init(self):
  r=received();d=ReceivedDemo(r);helper.classify_received(r,proof());helper.continue_unplayed(d,r,d.credentials(),proof());obs=r['remaining_baseline_observation'];self.assertEqual(obs['kind'],'native_init_balance_observation');self.assertEqual(obs['after_native'],{'game':0,'wallet':100000});self.assertEqual(r['checks'][1]['kind'],'dig_native_check_failure');self.assertFalse(r['checks'][1]['ok'])
 def test_untriggered_conditional_stays_needs_trigger_without_another_spin(self):
  r=received();r['declared_modes']=r['declared_modes'][:1]+[{'name':'conditional_card/c','command':'spin','options':{'bet':10},'cost_native':10,'conditional_card':True,'gamble_choice':'c','maximum_paid_attempts':1}];d=ReceivedDemo(r);helper.classify_received(r,proof());helper.continue_unplayed(d,r,d.credentials(),proof());self.assertEqual(r['modes'][1]['status'],'needs_trigger');self.assertEqual(r['modes'][1]['round_status'],'closed');self.assertEqual(sum(c[0]=='spin' for c in d.calls),1);self.assertFalse(any(c[0]=='gamble' for c in d.calls));self.assertEqual(r['remaining_declared_modes_status'],'partial')
 def test_offered_conditional_executes_only_exact_target_then_collects_and_retains_historical_failure(self):
  class Offered(ReceivedDemo):
   def call(self,command,options=None):
    response=super().call(command,options)
    if command=='spin':response['flow'].update(state='gamble',available_actions=['init','gamble','close']);response['balance']['game']=10;response['outcome']['win']=10;self.events[-1]['response']=copy.deepcopy(response)
    return response
  r=received();r['declared_modes']=r['declared_modes'][:1]+[{'name':'conditional_card/c','command':'spin','options':{'bet':10},'cost_native':10,'conditional_card':True,'gamble_choice':'c','maximum_paid_attempts':1}];d=Offered(r,win=True);helper.classify_received(r,proof());helper.continue_unplayed(d,r,d.credentials(),proof());self.assertEqual(d.calls,[('init',None),('spin',{'bet':10}),('gamble',{'bet':'c'}),('close',None)]);self.assertEqual(r['modes'][1]['gamble_choices_executed'],['c']);self.assertEqual(r['bonus_mode_coverage']['financially_verified_choices'],['c']);self.assertEqual(r['bonus_mode_coverage']['executed_not_financially_verified'],['s']);self.assertEqual(r['dig_bonus_operations'][0]['financial_status'],'failed');self.assertEqual(r['status'],'needs_review')
if __name__=='__main__':unittest.main()
