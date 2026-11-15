import unittest,json
from pathlib import Path
from volatility_modes import metadata,plan
class VolatilityModes(unittest.TestCase):
 def test_explicit_paid_values_and_deletion_before_free_spins(self):
  source='this.additionalSpinOptions.volatility=1==this.getCurrentVolatility()?"low":"medium";beforeGoFreespins(t){this.fsModeSwitcher(Number(i)),delete this.additionalSpinOptions.volatility}'
  m=metadata(source);self.assertEqual(m['paid_volatility_values'],['low','medium'])
  with self.assertRaises(ValueError):metadata(source.replace('delete this.additionalSpinOptions.volatility','unknown()'))
 def test_both_paid_values_and_purchase_levels_keep_native_prices(self):
  a=json.loads((Path(__file__).parent/'live/DiamondOfJungle.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'paid_volatility_values':['low','medium']});self.assertEqual(len(m),6);self.assertEqual([x['cost_native'] for x in m],[10,750,1500,10,750,1500]);self.assertEqual([x['options']['volatility'] for x in m],['low']*3+['medium']*3);self.assertTrue(all('continuation_options' not in x for x in m))
