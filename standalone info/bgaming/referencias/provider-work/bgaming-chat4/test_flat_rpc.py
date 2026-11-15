import unittest
from types import SimpleNamespace
from flat_rpc import metadata,plan,run
class FlatRPC(unittest.TestCase):
 def test_sweet_samurai_uses_native_bet_and_bet_type_without_buy_fields(self):
  s='body:{req:{bet:e,bet_type:n},state_lock:this.stateLock},playMethod:"play";t.resp.win'
  m=metadata(s);a={'result':{'currency':'FUN','currency_attributes':{'subunits':100},'config':{'bet_limits':[20,40]},'balance':100000,'state':None,'freebets':None}}
  self.assertEqual(plan(a,m)[0]['bet_native'],20)
  with self.assertRaises(ValueError):metadata(s+' purchased_feature')
 def test_incremental_native_wins_and_round_balance(self):
  replies=iter([{'balance':995,'resp':{'win':5},'final':False},{'balance':1005,'resp':{'win':10},'final':True}]);calls=[]
  h=SimpleNamespace(last={'balance':1000,'state':None},parent=SimpleNamespace(events=[],money_checks=[]))
  def request(method,req):calls.append(req);return {'result':next(replies)}
  h.request=request;x=run(h,{'bet_native':10,'cost_native':10});self.assertEqual(x['win_native'],15);self.assertEqual(calls,[{'bet':10,'bet_type':'bet'}]*2);self.assertTrue(h.parent.money_checks[0]['ok'])
