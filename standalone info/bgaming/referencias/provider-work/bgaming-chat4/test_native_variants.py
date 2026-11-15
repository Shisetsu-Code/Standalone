import json,unittest
from pathlib import Path
from native_variants import parse,plan,balanced,fields
P=Path(__file__).parent
class NativeModes(unittest.TestCase):
 def test_source_derived_wire_stakes_and_variant_costs(self):
  meta=json.loads((P/'protocols/SpiderCircusHoldAndWin.native-variants.json').read_text(encoding='utf8'));r=json.loads((P/'live/SpiderCircusHoldAndWin.json').read_text(encoding='utf8'))['events'][0]['response'];modes=plan(r,meta)
  self.assertEqual(len(meta['native_variants']),10);self.assertEqual(len(modes),15);self.assertTrue(all(m['options']['bet']==20 for m in modes));self.assertEqual([m['cost_native'] for m in modes],[20,1200,40,2400,60,3600,80,4800,100,6000,30,60,90,120,150]);self.assertEqual({m['options']['mode'] for m in modes},set(map(str,range(10))))
 def test_nested_data_is_read_without_evaluating_code(self):
  value='{name:"test",custom:{nested:"} unsafe()"},base_bet:20}';self.assertEqual(balanced(value,0),value);self.assertEqual(fields(value)['base_bet'],'20')
 def test_unknown_request_conversion_rejected(self):
  with self.assertRaises(ValueError):parse('globalThis.untrusted()')
if __name__=='__main__':unittest.main()
