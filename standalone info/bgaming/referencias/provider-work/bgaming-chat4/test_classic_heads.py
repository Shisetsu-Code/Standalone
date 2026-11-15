import json,unittest
from pathlib import Path
from classic_heads import plan,settled
class ClassicHeads(unittest.TestCase):
 def initial(self):return json.loads((Path(__file__).parent/'live/HeadsTails.json').read_text(encoding='utf8'))['events'][0]['response']
 def test_two_sides_use_native_minimum(self):
  modes=plan(self.initial(),{'classic_heads_verified':True});self.assertEqual([m['options'] for m in modes],[{'side':'head','bet':100},{'side':'tail','bet':100}])
 def test_winning_and_missing_zero_scalar_result(self):
  self.assertEqual(settled(100000,{'balance':100098,'result':198,'game':{'state':'closed','flip_result':'head'}},100)['win_native'],198)
  self.assertEqual(settled(100000,{'balance':99900,'game':{'state':'closed','flip_result':'tail'}},100)['win_native'],0)
 def test_native_discrepancy_or_unknown_outcome_not_hidden(self):
  with self.assertRaises(ValueError):settled(100000,{'balance':100099,'result':198,'game':{'state':'closed','flip_result':'head'}},100)
  with self.assertRaises(ValueError):settled(100000,{'balance':99900,'game':{'state':'closed','flip_result':'other'}},100)
