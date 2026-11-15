import unittest,json
from pathlib import Path
from classic_roulette import plan,spin_result,finish_result
class ClassicRoulette(unittest.TestCase):
 def test_all_advertised_bet_types_have_native_representatives(self):
  for gid in ['AmericanRoulette','EuropeanRoulette','FrenchRoulette']:
   a=json.loads((Path(__file__).parent/'live'/(gid+'.json')).read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'classic_roulette_verified':True});self.assertEqual(set(x['name'] for x in m),set(a['options']['bet_limits']));self.assertTrue(all(x['options'][0]['amount']==100 for x in m));self.assertTrue(all(type(x['options']) is list for x in m))
 def test_win_and_finish_are_independently_reconciled(self):
  r={'balance':10100,'result':{'total':200},'available_commands':['init','finish']};self.assertTrue(spin_result(10000,r,100)['ok']);self.assertTrue(finish_result(r,{'balance':10100,'available_commands':['init','spin']})['ok'])
  with self.assertRaises(ValueError):finish_result(r,{'balance':10101,'available_commands':['spin']})
