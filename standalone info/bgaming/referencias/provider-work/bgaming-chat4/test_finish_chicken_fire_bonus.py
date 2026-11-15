import copy,json,unittest
from types import SimpleNamespace
from pathlib import Path
import finish_chicken_fire_bonus as f
import four_modern_slots as x
import test_four_modern_slots as fixtures
ROOT=fixtures.ROOT
from resume_oga_combined import public_events

class ReceivedChicken(unittest.TestCase):
 def fixture(self,failure=False):
  helper=fixtures.FourModern();meta=helper.meta('ChickenFire');initial=helper.initial('ChickenFire');modes=x.plan(initial,meta);opening=json.loads((ROOT/'protocols/ChickenFire.received-native-bonus-fixture.json').read_text())['received_result'];events=[dict(status=200,request={'id':'rpc-1','method':'init','params':{}},response={'id':'rpc-1',**initial})]
  for i,balance in enumerate([99900,99750]):events.append(dict(status=200,request={'id':'rpc-'+str(i+2),'method':'play','params':{'req':modes[i]['req']}},response={'id':'rpc-'+str(i+2),'result':dict(final=True,balance=balance,round='prior-'+str(i),resp={'data':[{}],'totalWin':0})}))
  events.append(dict(status=200,request={'id':'rpc-4','method':'play','params':{'req':modes[2]['req']}},response={'id':'rpc-4','result':copy.deepcopy(opening)}))
  report=dict(game={'game_id':'ChickenFire'},protocol=x.PROTOCOL,status='needs_review',reason='Nonfinal ChickenFire has no source-proved API continuation',protocol_metadata=copy.deepcopy(meta),declared_modes=modes,modes=[dict(mode=modes[i],status='closed',first_event=i+1,last_event=i+1) for i in range(2)],events=public_events(events),checks=[{'ok':True},{'ok':True}])
  data=dict(fresh_demo=True,game_id='ChickenFire',status='received',initial=initial,events=copy.deepcopy(events),last_result=copy.deepcopy(opening),last_response=copy.deepcopy(events[-1]['response']),last_request=copy.deepcopy(events[-1]['request']),metadata=copy.deepcopy(meta))
  h=SimpleNamespace(initial=initial,metadata=meta,last=copy.deepcopy(opening),last_response=data['last_response'],raw_events=copy.deepcopy(events),parent=SimpleNamespace(events=report['events'],money_checks=report['checks']));calls=[];remaining=len(opening['resp']['data'])
  def request(method,req=None):
   nonlocal remaining
   calls.append(copy.deepcopy(req))
   if remaining:
    remaining-=1;result=dict(final=remaining==0,balance=93749 if failure else 108450 if remaining==0 else 93750,round=opening.get('round'))
   else:result=dict(final=True,balance=h.last['balance']-(9000 if req['feature_id']=='buy_super_bonus' else 12000),round=req['feature_id'],resp={'data':[{}],'totalWin':0})
   event=dict(status=200,request={'id':'next-'+str(len(calls)),'method':method,'params':{'req':copy.deepcopy(req)}},response={'result':result});h.raw_events.append(event);h.last=result;h.last_response=event['response'];return event['response']
  h.request=request;return h,report,data,meta,calls
 def test_received_paid_bonus_not_rebought_and_only_remaining_two_purchases_execute(self):
  h,report,data,meta,calls=self.fixture();old=data['events'][-1]['request'];stages=[];native=h.request
  result=f.execute(h,report,data,meta,gate=SimpleNamespace(check=lambda:None),persist=lambda stage,payload:stages.append(stage))
  self.assertEqual(result['status'],'complete_declared_modes');self.assertEqual(len(result['modes']),5);self.assertTrue(result['modes'][2]['recovered_received_paid_bonus']);self.assertEqual(result['modes'][2]['win_ratio'],[14700,1]);self.assertEqual(calls[:-2],[{'bet':100,'bet_type':'bet'}]*27);self.assertEqual([q['feature_id'] for q in calls[-2:]],['buy_super_bonus','buy_ultra_bonus']);self.assertNotIn(old['params']['req'],calls);self.assertEqual(result['modes'][-1]['final_balance'],87450);self.assertIs(h.request,native);self.assertIn('native_response_received_before_validation',stages);self.assertEqual(result['received_chicken_bonus_recovery']['audit_summary'],{'failed':0,'rounds':5,'closed':5})
 def test_first_stage_debit_failure_stops_without_new_purchase_or_retry(self):
  h,report,data,meta,calls=self.fixture(failure=True);result=f.execute(h,report,data,meta,gate=SimpleNamespace(check=lambda:None),persist=lambda *args:None)
  self.assertEqual(result['status'],'needs_review');self.assertEqual(calls,[{'bet':100,'bet_type':'bet'}]);self.assertFalse(result['checks'][-1]['ok']);self.assertEqual(len(result['events']),5)
 def test_failed_or_different_received_context_is_rejected_before_request(self):
  h,report,data,meta,calls=self.fixture();data['last_request']['params']['req']['feature_id']='buy_super_bonus'
  with self.assertRaises(ValueError):f.execute(h,report,data,meta,gate=SimpleNamespace(check=lambda:None),persist=lambda *args:None)
  self.assertFalse(calls)
 def test_once_archive_never_overwrites_original(self):
  import tempfile
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'original.json';f.once(path,b'original')
   with self.assertRaises(FileExistsError):f.once(path,b'changed')
   self.assertEqual(path.read_bytes(),b'original')
