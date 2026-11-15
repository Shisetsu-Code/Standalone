import unittest,json
from pathlib import Path
from native_play_modes import plan,settled
class NativePlayModes(unittest.TestCase):
 def test_distinct_mode_fields_and_mode_specific_native_minimum(self):
  p=Path(__file__).parent/'live'
  for gid,field,expected in [('DiceClash','game_mode',[10]*3),('StreetPower','game_type',[100,500,1000]),('FortuneSpin','game_mode',[4]*4)]:
   a=json.loads((p/(gid+'.json')).read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'native_play_selector':field,'native_play_catalog_key':'game_modes' if gid=='FortuneSpin' else 'game_types'})
   self.assertEqual([x['cost_native'] for x in m],expected);self.assertTrue(all(x['options']['bonus'] is False and field in x['options'] for x in m))
 def test_backend_stake_and_payout_are_checked(self):
  r={'game':{'state':'closed'},'balance':10003,'bets':{'initial':10,'win_amount':13}}
  self.assertTrue(settled(10000,r,10)['check']['ok']);r['bets']['initial']=1
  with self.assertRaises(ValueError):settled(10000,r,10)
