import unittest,json,pathlib,copy
from native import minimum_bet,terminal,audit
R=pathlib.Path(__file__).resolve().parent.parent
class NativeTests(unittest.TestCase):
 def setUp(self):
  p=R/'private/sessions/diamond-normal-probe-1';self.i=json.loads((p/'init.json').read_text())['response'];self.a=json.loads((p/'normal-0.json').read_text())
 def test_native_minimum(self):self.assertEqual(minimum_bet(self.i),{'@type':'BetParams','bet':30,'multiplier':1,'denomination':'0.010'})
 def test_actual_normal(self):self.assertEqual(audit(self.i,[self.a],'1')['cost'],'0.300')
 def test_wrong_balance_fails(self):
  a=copy.deepcopy(self.a);a['response']['balance']['amount']='999.800'
  with self.assertRaises(ValueError):audit(self.i,[a],'1')
 def test_initialized_feature_not_closed(self):
  a=copy.deepcopy(self.a['response']);a['states'].update(initialized='FREE_GAME',FREE_GAME={'status':'INIT','stepsAvailable':10})
  self.assertFalse(terminal(a))
 def test_active_feature_not_closed(self):
  a=copy.deepcopy(self.a['response']);a['states'].update(current='FREE_GAME',FREE_GAME={'status':'ACTIVE','stepsAvailable':3,'parentFeatureId':'SLOT'})
  self.assertFalse(terminal(a))
 def test_match3_current_native_contract(self):
  from live_actions import continuation
  c=json.loads((R/'private/rounds/199/NORMAL.json').read_text());i=json.loads((R/'private/sessions/game-199-1/init.json').read_text())['response'];s=(R/'private/sessions/game-199-1/client.js').read_text(encoding='utf-8')
  a=c['journal'][0]['response'];self.assertEqual(continuation(a,i,s,minimum_bet(i)),{'@type':'features.pickme.action.PickMeAction','choice':0})
  a=copy.deepcopy(a);a['states']['MATCH3']['choices'][0]=2;self.assertEqual(continuation(a,i,s,minimum_bet(i))['choice'],1)
  with self.assertRaises(ValueError):continuation(a,i,'',minimum_bet(i))
 def test_pickme_current_native_contract(self):
  from live_actions import continuation
  c=json.loads((R/'private/rounds/199/BUY_PICKME.json').read_text());i=json.loads((R/'private/sessions/game-199-1/init.json').read_text())['response'];s=(R/'private/sessions/game-199-1/client.js').read_text(encoding='utf-8');a=c['journal'][0]['response']
  self.assertEqual(continuation(a,i,s,minimum_bet(i)),{'@type':'features.pickme.action.PickMeAction','choice':0})
 def test_real_recovery_receipt_and_ledger(self):
  c=json.loads((R/'private/rounds/199/NORMAL.json').read_text());i=json.loads((R/c['init_reference']).read_text())['response']
  self.assertEqual(audit(i,c['journal'],'1')['balance_after'],'1499.500')
  c['journal'][1]['recovery_snapshot']['states']['MATCH3']['choices'][0]=-1
  with self.assertRaises(ValueError):audit(i,c['journal'],'1')
 def test_unknown_receipt_is_not_action_response(self):
  c=json.loads((R/'private/rounds/199/NORMAL.json').read_text());i=json.loads((R/c['init_reference']).read_text())['response'];c['journal'][1].pop('recovery_snapshot')
  with self.assertRaises(ValueError):audit(i,c['journal'],'1')
 def test_current_older_client_equivalent_packet(self):
  from campaign import client_contract
  s=(R/'private/sessions/game-107-1/client.js').read_text(encoding='utf-8');self.assertTrue(client_contract(s)['spin'])
 def test_native_legacy_pickme_only_packet(self):
  from campaign import client_contract
  s=(R/'private/sessions/game-62-1/client.js').read_text(encoding='utf-8');self.assertTrue(client_contract(s)['spin'])
 def test_native_legacy_without_purchase_field(self):
  from campaign import client_contract
  s=(R/'private/sessions/game-56-1/client.js').read_text(encoding='utf-8');contract=client_contract(s);self.assertTrue(contract['spin']);self.assertFalse(contract['buy_supported'])
if __name__=='__main__':unittest.main()
