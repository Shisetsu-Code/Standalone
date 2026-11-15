import json,unittest
from pathlib import Path
class LuckyDragonControls(unittest.TestCase):
 def test_source_controls_not_internal_price_registry(self):
  from lucky_dragon_controls import metadata,plan
  root=Path(__file__).resolve().parent
  source=next((root.parents[1]/'bgaming-private-chat4/research/legacy/LuckyDragonMultiDiceX').glob('*/bundle.js')).read_text(encoding='utf8')
  initial=json.loads((root/'live/LuckyDragonMultiDiceX.json').read_text())['events'][0]['response']
  modes=plan(initial,metadata(source));self.assertEqual(len(modes),3)
  self.assertEqual([m['cost_native'] for m in modes],[10,300,1000])
  self.assertTrue(all('purchased_feature_level' not in m['options'] for m in modes))
  self.assertEqual([m['options'].get('purchased_feature') for m in modes[1:]],['bonus_buy_0_chance','bonus_buy_1_chance'])
 def test_unproved_source_rejected(self):
  from lucky_dragon_controls import metadata
  with self.assertRaises(ValueError):metadata('bonus_buy_0_chance')
