import json,unittest,copy
from pathlib import Path
from cocos_adapter import plan,continuation
from cocos_audit import audit,get_win
P=Path(__file__).parent
class CocosEvidence(unittest.TestCase):
 def fixture(self):return json.loads((P/'transport/RedAndHotChilli.cocos-evidence.json').read_text(encoding='utf8'))
 def test_native_wallet_conservation_and_distinct_bids(self):
  d=self.fixture();checks,rounds=audit(d['initial'],d['events'],d['metadata']);self.assertTrue(all(x['ok'] for x in checks));self.assertEqual(len(rounds),6);self.assertEqual([r['cost_native'] for r in rounds],[100,130,8000,20000,8000,20000]);self.assertEqual(rounds[-1]['final_balance_native'],76170)
 def test_prices_are_not_round_base_stake(self):
  d=self.fixture();m=plan(d['initial'],d['metadata']);self.assertEqual([x['cost_native'] for x in m],[100,100,130,130,8000,8000,20000,20000]);self.assertEqual({x['bid'] for x in m},{0,1,2,3});self.assertEqual(m[4]['feature'],m[6]['feature'])
 def test_round_win_not_sum_of_steps_or_multiplier(self):
  self.assertEqual(get_win({'round':{'win':'7200'},'step':{'win':'7200','cd':'{"lvlrwd":100}'}}),7200);self.assertEqual(get_win({'round':{},'step':{}}),0)
 def test_unknown_state_never_guessed(self):
  with self.assertRaises(RuntimeError):continuation({'resp':{'step':{'er':[{'esmid':'OTHER_CHOICE'}]}}},{},'collect',False,set(),None)
 def test_risk_and_hidden_cell_request_shapes(self):
  meta={'gamble_req_values':{'collect':'no','gamble':'yes'},'board_symbols':{'Empty':18}}
  result={'resp':{'step':{'er':[{'esmid':'RISK'}]}}};extra,*_=continuation(result,meta,'gamble_once',False,set(),None);self.assertEqual(extra,{'custom_field':{'fid':{'a':'yes'}}})
  result={'resp':{'round':{'bet':{'id':3}},'step':{'er':[{'esmid':'FS2_PICK'}],'f':[[{'e':12},{'e':18}]]}}};extra,*_=continuation(result,meta,'collect',False,set(),None);self.assertEqual(extra,{'bid':3,'custom_field':{'fid':{'x':0,'y':1}}})
if __name__=='__main__':unittest.main()
