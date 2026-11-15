import copy,json,unittest
from pathlib import Path
from all_lucky_catalog_report import audit_variant
class SelectorAudit(unittest.TestCase):
 def sample(self):return json.loads((Path(__file__).parent/'live/selector-variants/AllLuckyClover5.json').read_text())
 def test_received_native_variant_closes(self):self.assertEqual(audit_variant(self.sample())['failed'],0)
 def test_modified_native_money_is_detected(self):
  r=self.sample();r['events'][-1]['response']['balance']['wallet']+=1;self.assertGreater(audit_variant(r)['failed'],0)
