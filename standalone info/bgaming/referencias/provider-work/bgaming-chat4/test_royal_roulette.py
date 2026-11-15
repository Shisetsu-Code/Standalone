import unittest,json
from pathlib import Path
from royal_roulette import plan,settled
class RoyalRoulette(unittest.TestCase):
 def test_thirteen_types_use_one_based_outside_features(self):
  a=json.loads((Path(__file__).parent/'live/RoyalRoulette500X.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'royal_roulette_verified':True});self.assertEqual(len(m),13)
  choices={x['name']:x['options']['bets'][0] for x in m};self.assertEqual(choices['column']['feature'],'1');self.assertEqual(choices['dozen']['feature'],'1');self.assertNotIn('feature',choices['red']);self.assertEqual({x['cost_native'] for x in m},{10})
 def test_native_balance_from_bet_array_and_payout(self):
  r={'balance':10010,'bets':{'win_amount':20},'game':{'state':'closed'}};self.assertTrue(settled(10000,r,10)['check']['ok']);r['balance']=10011
  with self.assertRaises(ValueError):settled(10000,r,10)
 def test_exact_native_float_zero_is_preserved(self):
  r={'balance':9990,'bets':{'win_amount':0.0},'game':{'state':'closed'}};x=settled(10000,r,10);self.assertEqual(x['win_native'],0.0);self.assertIs(type(x['win_native']),float)
