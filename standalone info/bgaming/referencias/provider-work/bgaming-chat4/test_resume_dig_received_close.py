import copy,importlib.util,json,unittest
from pathlib import Path
from test_resume_dig_choices import FakeDemo,proof
if importlib.util.find_spec('resume_dig_received_close'):
 import resume_dig_received_close as helper
else:helper=None
ROOT=Path(__file__).resolve().parent
def fixture():
 archive=ROOT/'live/attempts/DigDigDigger.before-received-close-finish.json';r=json.loads((archive if archive.exists() else ROOT/'live/DigDigDigger.json').read_text(encoding='utf8'));r['events']=r['events'][:17];r['modes']=r['modes'][:2];r.pop('dig_received_close_classified',None);r.pop('dig_received_close_init_observation',None);return r
class Demo(FakeDemo):
 def call(self,command,options=None):
  if command=='init':
   self.calls.append(('init',None));r=copy.deepcopy(self.events[0]['response']);r['balance']={'wallet':self.last_response['balance']['wallet']+self.last_response['balance']['game'],'game':0};r['flow']=dict(self.last_response['flow'],state='ready',command='init',available_actions=['init','spin']);self.last_response=r;self.events.append({'request':{'command':'init'},'response':copy.deepcopy(r),'status':200});return r
  r=super().call(command,options)
  if command=='spin' and options.get('purchased_feature_level'):r['flow']['purchased_feature']['level']=options['purchased_feature_level']
  if command=='freespin':r['outcome']['win']=10
  self.events[-1]['response']=copy.deepcopy(r);return r
class ReceivedClose(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(helper,'Received close slot helper required')
 def test_existing_close_is_classified_offline_from_original_trigger_without_replay(self):
  r=fixture();events=copy.deepcopy(r['events']);checks=copy.deepcopy(r['checks']);helper.classify_close(r,proof());self.assertEqual(r['events'],events);self.assertEqual(r['checks'][:len(checks)],checks);m=r['modes'][2];self.assertEqual((m['mode']['name'],m['first_event'],m['last_event'],m['win_native']),('freespin_buy:1',5,16,265));self.assertEqual(m['status'],'closed');self.assertTrue(r['bonus_mode_coverage']['collect_tested']);self.assertEqual(r['modes'][0]['financial_status'],'failed')
 def test_full_remaining_purchases_start_at_level_two_and_unoffered_cards_stay_pending(self):
  r=fixture();d=Demo(r);helper.execute(d,r,d.credentials(),proof());self.assertEqual(d.calls[0],('spin',{'bet':10,'purchased_feature':'freespin_buy','purchased_feature_level':'2'}));paid=[q for c,q in d.calls if c=='spin'];self.assertEqual(len(paid),14);self.assertFalse(any(q.get('purchased_feature_level')=='1' for q in paid));self.assertEqual(len(r['modes']),17);self.assertTrue(all(m['status']=='needs_trigger' for m in r['modes'][11:]));self.assertEqual(r['status'],'needs_review');self.assertEqual(r['remaining_declared_modes_status'],'partial')
 def test_explicit_init_conserves_pending_credit_and_is_a_separate_observation(self):
  r=fixture();d=Demo(r);helper.execute(d,r,d.credentials(),proof(),observe_init=True);self.assertEqual(d.calls[0],('init',None));obs=r['dig_received_close_init_observation'];self.assertEqual(obs['before_native'],{'game':265,'wallet':98884});self.assertEqual(obs['after_native'],{'game':0,'wallet':99149});self.assertTrue(obs['ok']);self.assertEqual(r['modes'][2]['final_balance'],{'game':265,'wallet':98884})
 def test_wrong_current_receipt_or_unowned_checkpoint_never_sends(self):
  for change in ['hash','owner','progressed']:
   r=fixture();d=Demo(r);c=d.credentials()
   if change=='hash':r['events'][16]['response_sha256']='wrong'
   if change=='owner':c['fresh_demo']=False
   if change=='progressed':r['modes'].append({'status':'closed'})
   with self.assertRaises(ValueError):helper.execute(d,r,c,proof())
   self.assertFalse(d.calls)
 def test_optional_init_with_unexplained_native_refresh_stops_before_paid_modes(self):
  class Refresh(Demo):
   def call(self,command,options=None):
    r=super().call(command,options)
    if command=='init':r['balance']['wallet']+=1;self.events[-1]['response']=copy.deepcopy(r)
    return r
  r=fixture();d=Refresh(r);helper.execute(d,r,d.credentials(),proof(),observe_init=True);self.assertEqual(d.calls,[('init',None)]);self.assertEqual(r['status'],'needs_review');self.assertFalse(r['dig_received_close_init_observation']['ok']);self.assertEqual(len(r['modes']),3)
 def test_offered_conditional_targets_each_execute_once_without_clearing_historic_failure(self):
  class Offered(Demo):
   def call(self,command,options=None):
    response=super().call(command,options)
    if command=='spin' and self.active_mode.get('conditional_card'):
     response['flow'].update(state='gamble',available_actions=['init','gamble','close']);response['balance']['game']=10;response['outcome']['win']=10;self.events[-1]['response']=copy.deepcopy(response)
    return response
  r=fixture();d=Offered(r);helper.execute(d,r,d.credentials(),proof());self.assertEqual([q['bet'] for c,q in d.calls if c=='gamble'],['s','c','d','h','black','red']);self.assertTrue(all(m['status']=='closed' for m in r['modes'][11:]));self.assertEqual(r['bonus_mode_coverage']['executed_not_financially_verified'],['s']);self.assertEqual(r['modes'][0]['financial_status'],'failed');self.assertEqual(r['remaining_declared_modes_status'],'complete');self.assertEqual(r['status'],'needs_review')
if __name__=='__main__':unittest.main()
