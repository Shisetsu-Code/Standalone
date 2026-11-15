import json,unittest
from pathlib import Path
from types import SimpleNamespace
from hyperhive_adapter import Hyperhive,plan_modes
from rpc_audit_hotrocket import audit_rpc
P=Path(__file__).parent
class HyperhiveEvidence(unittest.TestCase):
 def fixture(self):return json.loads((P/'HotRocketMegaPotz.rpc.reference.json').read_text(encoding='utf8'))
 def metadata(self):return json.loads((P/'protocols/HotRocketMegaPotz.json').read_text(encoding='utf8'))
 def test_recorded_rounds_and_deferred_wallet_credit(self):
  data=self.fixture();checks,rounds=audit_rpc(data['initial'],data['events']);self.assertTrue(all(x['ok'] for x in checks));self.assertEqual(len(checks),53);self.assertEqual([r['cost_native'] for r in rounds],[20,28,2000,2000,4000]);self.assertEqual([r['win_native'] for r in rounds],[0,0,373,232,2950]);self.assertEqual(rounds[-1]['final_balance_native'],95507)
 def test_actual_feature_mapping_filters_global_aliases(self):
  meta=self.metadata();self.assertEqual(meta['features'],{'freespin_chance':'1.4','freespin_buy':'100','high_freespin_buy':'200'});self.assertEqual(meta['choices'],{'gamble':2,'collect':1});modes=plan_modes(self.fixture()['initial'],meta);self.assertEqual([m['cost_native'] for m in modes],[20,20,28,28,2000,2000,4000,4000])
 def test_open_state_cannot_start_new_purchase(self):
  h=Hyperhive.__new__(Hyperhive);h.parent=SimpleNamespace(events=[],money_checks=[]);h.last={'final':False,'balance':100000};h.offers=set();calls=[];h.request=lambda *a:calls.append(a)
  with self.assertRaises(RuntimeError):h.run_mode({'feature':'freespin_buy','cost_native':2000,'bet_native':20,'policy':'collect'},None)
  self.assertEqual(calls,[])
 def test_unknown_choice_never_submitted(self):
  h=Hyperhive.__new__(Hyperhive);h.parent=SimpleNamespace(events=[],money_checks=[]);h.last={'final':True,'balance':100000};h.offers=set();h.metadata={'choices':{}};calls=[]
  def request(method,req):
   calls.append(req);return {'result':{'final':False,'balance':99980,'resp':{'win':0,'engine':{'gamestate':{'totalStake':20,'triggeringDetails':{'nextAction':['unknownA','unknownB']}}}}}}
  h.request=request
  with self.assertRaises(RuntimeError):h.run_mode({'feature':None,'cost_native':20,'bet_native':20,'policy':'collect'},None)
  self.assertEqual(len(calls),1)
 def test_conditional_gamble_skips_if_not_offered(self):
  h=Hyperhive.__new__(Hyperhive);h.offers=set();h.request=lambda *a:self.fail('Should not send a request')
  result=h.run_mode({'feature':'high_freespin_buy','conditional_gamble':True},None);self.assertEqual(result['status'],'not_applicable');self.assertEqual(result['network_calls'],0)
if __name__=='__main__':unittest.main()
