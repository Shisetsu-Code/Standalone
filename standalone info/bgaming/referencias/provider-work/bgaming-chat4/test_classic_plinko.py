import unittest,json,copy
from pathlib import Path
from classic_plinko import metadata,plan,closed_result
P=Path(__file__).parent
class ClassicPlinko(unittest.TestCase):
 def test_official_sibling_clients_are_prepared_explicitly(self):
  from unittest.mock import patch
  from legacy_metadata import prove_classic_plinko
  source='playGame(t,e,i){return request({options:{bet:t,risk_level:e,rows:i}})}win:r.result,totalBet:x'
  for gid in ['EasterPlinko','PlinkoXY']:
   with patch('legacy_metadata.load_client',return_value=({},source)),patch('legacy_metadata.save'):
    self.assertTrue(prove_classic_plinko(gid,None)['classic_plinko_verified'])
 def initial(self):return json.loads((P/'live/Plinko.json').read_text(encoding='utf8'))['events'][0]['response']
 def test_all_native_risk_row_modes(self):
  modes=plan(self.initial(),{'classic_plinko_verified':True});self.assertEqual(len(modes),27);self.assertEqual({m['cost_native'] for m in modes},{100});self.assertEqual({m['options']['rows'] for m in modes},set(range(8,17)))
 def test_currency_and_shape_not_inferred(self):
  initial=self.initial();initial['options']['currency']['code']='USD'
  with self.assertRaises(ValueError):plan(initial,{'classic_plinko_verified':True})
  with self.assertRaises(ValueError):metadata('unrecognized source')
 def test_native_scalar_payout_checked_against_balance(self):
  response={'balance':9950,'result':50,'game':{'state':'closed'}};self.assertEqual(closed_result(10000,response,100)['win_native'],50)
  response['balance']=9951
  with self.assertRaises(ValueError):closed_result(10000,response,100)
 def test_unknown_continuation_retained(self):
  with self.assertRaises(ValueError):closed_result(10000,{'balance':9900,'result':0,'game':{'state':'choice'}},100)
