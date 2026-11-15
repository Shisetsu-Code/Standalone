import unittest,json
from pathlib import Path
from playson_source import inspect_bet_builders,title_key
ROOT=Path(__file__).resolve().parents[2]
class PlaysonSourceTests(unittest.TestCase):
 def test_inspected_real_clients_bind_purchase_and_ante_xml(self):
  rows=json.loads((ROOT/'playson-private-root/resolved-new-bindings.json').read_text())
  for b in rows:
   s=(ROOT/'playson-private-root/scripts'/(b['source_sha256']+'.js')).read_text(encoding='utf8');p=inspect_bet_builders(s);self.assertTrue(p['supported']);self.assertTrue(p['purchase_binding']);self.assertTrue(p['ante_binding'])
 def test_unknown_paid_xml_is_not_certified(self):
  s='t.prototype.createBetMessage=function(e){var n=a.prototype.createBetMessage.call(this,e);n.append("<secret_paid_option/>");return n}'
  self.assertFalse(inspect_bet_builders(s)['supported'])
 def test_single_legacy_buy_has_explicit_request_style(self):
  source='t.prototype.createBetMessage=function(e){var n=a.prototype.createBetMessage.call(this,e);if(g.buyFeatureConfirmed)n.append(\'<buy bonus_game="true"/>\');return n}'
  p=inspect_bet_builders(source);self.assertTrue(p['supported']);self.assertEqual(p['purchase_style'],'untyped_bonus_game')

 def test_title_matching_ignores_punctuation_but_preserves_game_identity(self):
  self.assertEqual(title_key('3 Roaring Bells: Hold and Win'),title_key('3 ROARING BELLS - Hold and Win'))
  self.assertNotEqual(title_key('Thunder Coins XXL: Multicoin'),title_key('Thunder Coins XXL: BoosterCells'))
if __name__=='__main__':unittest.main()
