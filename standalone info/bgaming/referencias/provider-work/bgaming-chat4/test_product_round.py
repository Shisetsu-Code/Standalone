import json,unittest
from pathlib import Path
from types import SimpleNamespace
from product_round_rpc import plan,run
P=Path(__file__).parent
class ProductRound(unittest.TestCase):
 def test_alternate_product_id_field_is_preserved_in_wire_and_audit(self):
  from product_round_rpc import metadata,audit
  source='const n={bet:t,purchased_feature:e,bonus_buy:s};this._getPlayResponse();function f(){return[{id:"wild",price:6,purchaseFeature:"buy_chance"}]}'
  meta=metadata(source,['buy_chance']);self.assertEqual(meta['product_wire_id_field'],'bonus_buy')
  initial={'result':{'balance':1000,'currency':'FUN','currency_attributes':{'subunits':100,'exponent':2},'config':{'bet_limits':[10]},'freebets':None,'state':None}};mode=plan(initial,meta)[1];calls=[];events=[]
  def request(method,req):
   calls.append(req);event={'request':{'method':method,'params':{'req':req}},'response':{'result':{'balance':940,'final':True,'resp':{'round':{'win':0}}}}};events.append(event);return event['response']
  h=SimpleNamespace(last=initial['result'],request=request,parent=SimpleNamespace(events=[],money_checks=[]));run(h,mode);self.assertEqual(calls[0]['bonus_buy'],'wild');self.assertNotIn('buy_id',calls[0]);checks,rounds=audit(initial,events,meta);self.assertTrue(checks[0]['ok'])
 def test_registry_keeps_different_prices_for_same_feature_alias(self):
  m=json.loads((P/'protocols/GatesOfPower.product-round.json').read_text(encoding='utf8'));initial={'result':{'currency':'FUN','currency_attributes':{'subunits':100,'exponent':2},'config':{'bet_limits':[10,20]},'freebets':None,'state':None}}
  modes=plan(initial,m);self.assertEqual([x['cost_native'] for x in modes],[10,20,100,900,1000,5000]);self.assertEqual([x['product_id'] for x in modes], [None,'boost','bns','enhance','bonus','super']);self.assertTrue(modes[1]['hidden_registry_product'])
 def test_missing_final_does_not_start_another_round(self):
  calls=[];h=SimpleNamespace(last={'balance':100000,'state':None},parent=SimpleNamespace(events=[],money_checks=[]))
  def request(*args):calls.append(args);return {'result':{'balance':99990,'resp':{'round':{'win':0}}}}
  h.request=request
  with self.assertRaises(RuntimeError):run(h,{'bet_native':10,'cost_native':10,'product_id':None})
  self.assertEqual(len(calls),1)
 def test_open_round_never_starts_purchase(self):
  h=SimpleNamespace(last={'balance':100000,'final':False},request=lambda *a:self.fail('Unexpected play'))
  with self.assertRaises(RuntimeError):run(h,{})
 def test_recorded_six_product_rounds_reconcile(self):
  from product_round_rpc import audit
  report=json.loads((P/'live/GatesOfPower.json').read_text(encoding='utf8'));checks,rounds=audit(report['events'][0]['response'],report['events'],report['protocol_metadata'])
  self.assertEqual(len(rounds),6);self.assertTrue(all(c['ok'] for c in checks));self.assertTrue(all(r['closed'] for r in rounds));self.assertEqual(rounds[-1]['final_balance_native'],95651);self.assertEqual([r['buy_id'] for r in rounds],[None,'boost','bns','enhance','bonus','super'])
if __name__=='__main__':unittest.main()
