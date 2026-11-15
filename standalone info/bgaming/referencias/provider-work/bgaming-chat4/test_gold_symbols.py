import unittest,json
from pathlib import Path
from gold_symbols import metadata,plan
P=Path(__file__).parent
class GoldSymbols(unittest.TestCase):
 def test_five_native_levels_and_features(self):
  a=json.loads((P/'live/Maneki88Fortunes.json').read_text(encoding='utf8'))['events'][0]['response'];meta={'gold_symbols_factors':{'1':8,'2':18,'3':38,'4':68,'5':88},'feature_default_base_bet':100,'price_rounding':{'purchase':'ceil','antebet':'ceil'}};modes=plan(a,meta)
  self.assertEqual(len(modes),15);self.assertEqual([m['cost_native'] for m in modes[::3]],[8,18,38,68,88]);self.assertEqual(modes[1]['cost_native'],440);self.assertEqual(modes[2]['cost_native'],12)
  self.assertTrue(all(m['options']['bet']==1 for m in modes));self.assertEqual(modes[-1]['options']['gold_symbols_count'],'5');self.assertTrue(all('continuation_options' not in m for m in modes))
 def test_source_proof_is_required(self):
  with self.assertRaises(ValueError):metadata('unknown')
 def test_missing_deletion_proof_blocks_live_contract(self):
  source='additionalSpinOptions.gold_symbols_count=""+t;BET_BY_SPECIAL_LVL=X;X={1:8,2:18,3:38,4:68,5:88};a*this.BET_BY_SPECIAL_LVL[x];this.BET_BY_SPECIAL_LVL[this.goldSymbolsLevel];for(var n in i)i[n]=i[n]*this.BET_BY_SPECIAL_LVL[n];'
  with self.assertRaises(ValueError):metadata(source)
  proved=metadata(source+'beforeGoFreespins(t,e){super.beforeGoFreespins(t,e),delete this.additionalSpinOptions.gold_symbols_count}')
  self.assertTrue(proved['gold_symbols_removed_before_freespins'])
