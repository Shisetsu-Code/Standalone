import unittest,json
from pathlib import Path
from indexed_rows import metadata,plan
class IndexedRows(unittest.TestCase):
 def test_source_explicit_row_range_and_native_minimum_index(self):
  source='Xs=3,Hs=5,Fs={5:20,4:10,3:5};this.reelSize=Hs;this.additionalSpinOptions.rows=this.reelSize;this.initialAvailableBets[this.reelSize-Xs];changeReelsSize(t){var i=Fs[this.reelSize];}'
  self.assertEqual(metadata(source)['indexed_rows'],{'values':[3,4,5],'minimum_index_base':3,'wire_type':'integer'})
  with self.assertRaises(ValueError):metadata(source.replace('Xs=3','Xs=unknown'))
 def test_each_row_uses_its_source_indexed_native_minimum(self):
  initial=json.loads((Path(__file__).parent/'live/BigAtlantisFrenzy.json').read_text(encoding='utf8'))['events'][0]['response'];meta={'indexed_rows':{'values':[3,4,5],'minimum_index_base':3,'wire_type':'integer'},'source_verified':True,'feature_default_base_bet':100};modes=plan(initial,meta);self.assertEqual([m['cost_native'] for m in modes],[10,20,800,20,40,1600,30,60,2400]);self.assertEqual([m['options']['bet'] for m in modes],[10]*3+[20]*3+[30]*3);self.assertTrue(all(type(m['options']['rows']) is int for m in modes));self.assertTrue(all(m['continuation_options']=={'rows':m['options']['rows']} for m in modes))
