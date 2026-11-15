import copy,importlib.util,json,unittest
from pathlib import Path
from types import SimpleNamespace
import blackjack_extra as bj
if importlib.util.find_spec('resume_blackjack_received'):
 import resume_blackjack_received as helper
else:helper=None
ROOT=Path(__file__).resolve().parent;PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def fixture():
 archive=ROOT/'live/attempts/SurrenderMultihandBlackjack.before-received-surrender-finish.json';r=json.loads((archive if archive.exists() else ROOT/'live/SurrenderMultihandBlackjack.json').read_text(encoding='utf8'));r['events']=r['events'][:26];r['modes']=r['modes'][:7];return r
def proof():
 r=fixture();source=next((PRIVATE/'research/legacy/SurrenderMultihandBlackjack').rglob('bundle.js')).read_text(encoding='utf8');return dict(r['protocol_metadata'],**bj.metadata(source,'SurrenderMultihandBlackjack'))
class Demo:
 def __init__(self,r):
  self.game=r['game'];self.events=r['events'];self.money_checks=r['checks'];self.last_response=copy.deepcopy(self.events[-1]['response']);self.prev=None;self.series='round_series_id-1';self.clean=SimpleNamespace(clean=lambda x:copy.deepcopy(x));self.calls=[];self.remaining=[]
 def call(self,command,options=None):
  self.calls.append((command,options));assert command=='finish' and options is None
  r=copy.deepcopy(self.last_response);r['game'].update(state='finished',action='finish');r['available_commands']=['init','start'];self.last_response=r;self.events.append({'request':{'command':'finish'},'response':copy.deepcopy(r),'status':200,'time':'synthetic-finish'});return r
 def run_mode(self,mode,initial):
  self.remaining.append(mode['name']);return dict(mode=mode,status='needs_trigger',round_status='closed',final_state='finished',final_balance=self.last_response['balance'])
 def credentials(self):return dict(fresh_demo=True,game_id='SurrenderMultihandBlackjack',operation={'status':'received'},series=self.series,last_response=copy.deepcopy(self.last_response))
class ReceivedBlackjack(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(helper,'Guarded received-surrender CLI required')
 def test_first_and_only_original_round_action_is_finish_then_remaining_declared_modes(self):
  r=fixture();old_modes=copy.deepcopy(r['modes']);d=Demo(r);saved=[];helper.execute(d,r,d.credentials(),proof(),persist=lambda:saved.append(len(d.events)));self.assertEqual(d.calls,[('finish',None)]);self.assertEqual(r['modes'][:7],old_modes);self.assertEqual(r['modes'][7]['mode']['name'],'area_1/surrender');self.assertTrue(r['modes'][7]['normalized_existing_received_surrender']);self.assertEqual(d.remaining,[m['name'] for m in r['declared_modes'][8:]]);self.assertEqual(len(r['modes']),len(r['declared_modes']));self.assertTrue(saved)
 def test_raw_engine_win_200_and_original_events_preserved_but_native_refund_is_50(self):
  r=fixture();events=copy.deepcopy(r['events']);d=Demo(r);helper.execute(d,r,d.credentials(),proof());self.assertEqual(r['events'][:26],events);self.assertEqual(r['events'][25]['response']['areas'][0]['main']['win_amount'],200);checks=[c for c in r['checks'] if c.get('normalized_received_surrender')];self.assertEqual(checks[-1]['native_surrender_refund'],50);self.assertEqual(r['received_blackjack_recovery_audit']['failed'],0);self.assertEqual(r['status'],'partial')
 def test_source_hash_mismatch_or_wrong_pending_mode_or_private_checkpoint_never_sends(self):
  for which in ['hash','mode','native']:
   r=fixture();d=Demo(r);p=proof();c=d.credentials()
   if which=='hash':p['source_sha256']='other'
   if which=='mode':r['declared_modes'][7]['name']='area_2/surrender'
   if which=='native':c['last_response']['balance']+=1
   with self.assertRaises(ValueError):helper.execute(d,r,c,p)
   self.assertFalse(d.calls)
 def test_unowned_or_progressed_checkpoint_is_not_resumed(self):
  r=fixture();d=Demo(r);c=d.credentials();c['fresh_demo']=False
  with self.assertRaises(ValueError):helper.execute(d,r,c,proof())
  self.assertFalse(d.calls)
  r=fixture();r['modes'].append({'status':'closed'});d=Demo(r)
  with self.assertRaises(ValueError):helper.execute(d,r,d.credentials(),proof())
  self.assertFalse(d.calls)
 def test_uncertain_finish_is_preserved_and_remaining_modes_never_start(self):
  r=fixture();d=Demo(r)
  def uncertain(command,options=None):
   d.calls.append((command,options));d.events.append({'request':{'command':command},'status':'uncertain'});raise RuntimeError('Synthetic uncertain finish')
  d.call=uncertain;helper.execute(d,r,d.credentials(),proof());self.assertEqual(d.calls,[('finish',None)]);self.assertFalse(d.remaining);self.assertEqual(r['status'],'needs_review');self.assertEqual(r['events'][-1]['status'],'uncertain');self.assertEqual(len(r['modes']),7)
 def test_runner_pause_and_future_timestamp_guards(self):
  with self.assertRaises(RuntimeError):helper.guard({'active_game':'another'},'PAUSE',10)
  with self.assertRaises(RuntimeError):helper.guard({'active_game':None},'CONTINUE',10)
  with self.assertRaises(ValueError):helper.guard({'active_game':None,'last_launch_epoch':11},'PAUSE',10)
  self.assertEqual(helper.guard({'active_game':None,'last_launch_epoch':0},'PAUSE',10),50)
if __name__=='__main__':unittest.main()
