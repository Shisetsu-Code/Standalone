import unittest,json
from pathlib import Path
from scratch_packs import plan
class ScratchPacks(unittest.TestCase):
 def test_all_three_boards_and_nine_native_pack_prices(self):
  a=json.loads((Path(__file__).parent/'live/ThreeKingsScratch.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'scratch_packs_verified':True});self.assertEqual(len(m),12);self.assertEqual([x['cost_native'] for x in m],[500,4500,20000,37500,1000,9000,40000,75000,2000,18000,80000,150000]);self.assertEqual({x['options']['mode'] for x in m},{'12','16','20'});self.assertTrue(all(x['continuation_options']['bet']==100 and not x['continuation_options']['bonus'] for x in m))
 def test_disabled_or_new_pack_schema_blocks_instead_of_guessing(self):
  a=json.loads((Path(__file__).parent/'live/ThreeKingsScratch.json').read_text(encoding='utf8'))['events'][0]['response'];a['options']['available_modes'].append('24')
  with self.assertRaises(ValueError):plan(a,{'scratch_packs_verified':True})
