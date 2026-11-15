import copy,importlib.util,json,unittest
from pathlib import Path
from types import SimpleNamespace
import final_rpc_pair as pair
from test_final_rpc_pair import source,yommi
if importlib.util.find_spec('resume_yommi_received_normal'):
 import resume_yommi_received_normal as helper
else:helper=None
ROOT=Path(__file__).resolve().parent
def fixture():
 archive=ROOT/'live/attempts/YommiRush.before-received-yommi-normal.json';r=json.loads((archive if archive.exists() else ROOT/'live/YommiRush.json').read_text(encoding='utf8'));r['events']=r['events'][:2];r['modes']=[];r['checks']=[];r.pop('received_yommi_normal_classified',None);return r
def proof(r):return pair.metadata('YommiRush',source('YommiRush'),r['events'][0]['response']['result']['config']['purchased_features'])
def credentials(r):return dict(fresh_demo=True,game_id='YommiRush',status='received',events=copy.deepcopy(r['events']),initial=copy.deepcopy(r['events'][0]['response']),last_result=copy.deepcopy(r['events'][-1]['response']['result']),last_response=copy.deepcopy(r['events'][-1]['response']),last_request=copy.deepcopy(r['events'][-1]['request']))
class Hyper:
 def __init__(self,r):
  self.parent=SimpleNamespace(game=r['game'],events=r['events'],money_checks=r['checks']);self.metadata=proof(r);self.initial=r['events'][0]['response'];self.last=copy.deepcopy(r['events'][-1]['response']['result']);self.raw_events=copy.deepcopy(r['events']);self.calls=[]
 def request(self,method,req=None):
  self.calls.append(copy.deepcopy(req));feature=req['purchased_feature'];cost=20*self.metadata['features'][feature];result=yommi(cost,0,0,True,self.last['balance']-cost,feature=feature);result.pop('round');result.pop('step');self.last=result;rid='rpc-'+str(len(self.raw_events)+1);q={'id':rid,'method':method,'params':{'req':copy.deepcopy(req),'state_lock':'synthetic-owned-lock'}};outer={'id':rid,'jsonrpc':'2.0','result':result};event={'request':q,'response':outer,'status':200};self.raw_events.append(copy.deepcopy(event));self.parent.events.append(copy.deepcopy(event));return outer
class ReceivedYommi(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(helper,'Received Yommi normal helper required')
 def test_offline_normalization_uses_actual_closed_response_without_playing_again(self):
  r=fixture();before=copy.deepcopy(r['events']);helper.classify_received(r,credentials(r),proof(r));self.assertEqual(r['events'],before);self.assertEqual(r['modes'][0]['status'],'closed');self.assertEqual(r['modes'][0]['final_balance'],99980);self.assertEqual(r['modes'][0]['identifier_policy'],'both_absent');self.assertTrue(r['checks'][-1]['ok']);self.assertEqual(r['status'],'partial')
 def test_only_remaining_three_purchases_are_sent_with_native_string_bet(self):
  r=fixture();h=Hyper(r);helper.execute(h,r,credentials(r),proof(r));self.assertEqual([q['purchased_feature'] for q in h.calls],['buy_chance','buy_bonus','buy_bonus_and_chance']);self.assertTrue(all(q['bet']=='20' for q in h.calls));self.assertEqual(len(r['modes']),4);self.assertEqual(r['status'],'complete_declared_modes');self.assertEqual(r['modes'][0]['first_event'],1);self.assertEqual(r['modes'][0]['last_event'],1);self.assertTrue(all(m['identifier_policy']=='both_absent' for m in r['modes']))
 def test_unowned_wrong_checkpoint_or_changed_native_normal_rejects_without_call(self):
  for kind in ['fresh','checkpoint','money']:
   r=fixture();h=Hyper(r);c=credentials(r)
   if kind=='fresh':c['fresh_demo']=False
   if kind=='checkpoint':c['last_result']['balance']+=1
   if kind=='money':r['events'][1]['response']['result']['balance']+=1;c=credentials(r)
   with self.assertRaises(ValueError):helper.execute(h,r,c,proof(r))
   self.assertFalse(h.calls)
 def test_partial_or_mixed_identity_policy_is_never_fabricated(self):
  r=fixture();r['events'][1]['response']['result']['round']='unexpected';c=credentials(r)
  with self.assertRaises(ValueError):helper.classify_received(r,c,proof(r))
  r=fixture();h=Hyper(r);real=h.request
  def mixed(method,req=None):
   result=real(method,req);result['result']['round']='now-present';result['result']['step']=1;h.raw_events[-1]['response']=copy.deepcopy(result);h.parent.events[-1]['response']=copy.deepcopy(result);return result
  h.request=mixed;helper.execute(h,r,credentials(r),proof(r));self.assertEqual(r['status'],'needs_review');self.assertEqual(len(h.calls),1)
 def test_absent_policy_needs_correlated_rpc_and_state_lock(self):
  r=fixture();r['events'][1]['response']['id']='wrong'
  with self.assertRaises(ValueError):helper.classify_received(r,credentials(r),proof(r))
  r=fixture();r['events'][1]['request']['params'].pop('state_lock')
  with self.assertRaises(ValueError):helper.classify_received(r,credentials(r),proof(r))
if __name__=='__main__':unittest.main()
