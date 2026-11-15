import unittest,json,copy
from pathlib import Path
from classic_gamble import metadata,check_event,check_finish
class ClassicGamble(unittest.TestCase):
 def source(self):return 'command:A.isApi2?"gamble":"check_card",options:{bet:t,additionalInfo:e};Re.gamble(t).then(x);'+''.join('onClick:"currentScene.playGamble`'+v+'";' for v in ['s','c','d','h','black','red'])
 def test_semantic_choice_values_not_scaled_as_money(self):self.assertEqual(metadata(self.source())['classic_gamble_choices'],['s','c','d','h','black','red'])
 def test_unproved_wire_or_unknown_ui_choice_blocks_probe(self):
  with self.assertRaises(ValueError):metadata(self.source().replace('additionalInfo:e','other:e'))
  with self.assertRaises(ValueError):metadata(self.source().replace('playGamble`red','playGamble`unknown'))
 def test_captured_suit_gamble_native_stake_and_payout(self):
  fixture=json.loads((Path(__file__).parent/'AztecMagicDeluxe.gamble.reference.json').read_text(encoding='utf8'));check=check_event(fixture['before'],fixture['event'],metadata(self.source()));self.assertEqual(check['stake_native'],6);self.assertEqual(check['payout_native'],24);self.assertEqual(check['actual'],100009);self.assertTrue(check['ok'])
  fixture['event']['response']['balance']=100010
  with self.assertRaises(ValueError):check_event(fixture['before'],fixture['event'],metadata(self.source()))
 def test_finish_does_not_credit_the_existing_prize_again(self):
  check=check_finish({'balance':100009,'available_commands':['finish']},{'balance':100009,'game':{'state':'closed'}},{'finish_command_verified':True});self.assertTrue(check['ok'])
 def test_captured_loss_omits_result_and_is_not_replayed(self):
  fixture=json.loads((Path(__file__).parent/'AztecMagicDeluxe.gamble-loss.reference.json').read_text(encoding='utf8'));meta=metadata(self.source());meta['v1_result_total_verified']=True;check=check_event(fixture['before'],fixture['event'],meta);self.assertEqual(check['stake_native'],24);self.assertEqual(check['payout_native'],0);self.assertEqual(check['actual'],99985)
