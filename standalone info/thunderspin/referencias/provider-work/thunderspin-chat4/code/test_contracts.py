import unittest
from pathlib import Path
import contracts
ROOT=Path(__file__).resolve().parent.parent
class ContractTests(unittest.TestCase):
 def test_modern_and_legacy_root_codes_come_from_native_configuration(self):
  modern=contracts.identify((ROOT/'client-index.js').read_text(encoding='utf-8'))
  legacy=contracts.identify((ROOT/'client-index.85458dfe.chunk.js').read_text(encoding='utf-8'))
  self.assertEqual(modern['slotcode'],'dragonhuntmegaways');self.assertEqual(legacy['slotcode'],'qos')
  self.assertTrue(modern['roll_lines']);self.assertFalse(legacy['roll_lines'])
 def test_unknown_code_or_external_service_cannot_generate_contract(self):
  with self.assertRaises(ValueError):contracts.identify('')
 def test_native_hyphenated_root_identifier_is_preserved(self):
  x=contracts.identify((ROOT/'private/references/illuminati-party/client.js').read_text(encoding='utf-8'))
  self.assertEqual(x['slotcode'],'illuminati-party')
 def test_illuminati_bonus_is_certified_roll_but_wheel_is_not(self):
  s=(ROOT/'private/references/illuminati-party/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'NextMode':'bonus','nextmodetype':'Freespin','FreeSpinsLeft':3,'waitForAcceptWin':False},s))
  self.assertTrue(contracts.roll_continuation({'Mode':'bonus','NextMode':'bonus','FreeSpinsLeft':3,'waitForAcceptWin':False},s))
  self.assertFalse(contracts.roll_continuation({'NextMode':'freespins_alternative','waitForAcceptWin':False},s))
 def test_secret_party_native_expand_group_is_roll_continuation(self):
  s=(ROOT/'private/references/secret-party/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'freespins','NextMode':'fs-expand','FreeSpinsLeft':8,'waitForAcceptWin':False},s))
  self.assertFalse(contracts.roll_continuation({'NextMode':'invented','waitForAcceptWin':False},s))
 def test_jingle_native_enum_group_is_resolved_without_guessing(self):
  s=(ROOT/'private/references/jingle-blast/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'freespins','NextMode':'fsrespins','FreeSpinsLeft':12,'waitForAcceptWin':False},s))
 def test_named_buy_contract_uses_native_code_and_declared_price(self):
  s=(ROOT/'private/references/indian-call/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.identify(s)['named_buy_contract'])
  self.assertFalse(contracts.identify((ROOT/'client-index.js').read_text(encoding='utf-8'))['named_buy_contract'])
 def test_aztec_automatic_free_mode_omits_disabled_accept_flag(self):
  s=(ROOT/'private/references/aztec-artefacts-10000/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'NextMode':'freespins','FreeSpinsLeft':12},s))
  self.assertFalse(contracts.roll_continuation({'NextMode':'freespins','waitForAcceptWin':True},s))
 def test_pyramids_free_round_does_not_require_a_gamble_decision(self):
  for slug in ['pyramids-deluxe','book-of-games-20']:
   s=(ROOT/'private/references'/slug/'client.js').read_text(encoding='utf-8')
   self.assertTrue(contracts.roll_continuation({'NextMode':'freespins','FreeSpinsLeft':10},s))
   self.assertFalse(contracts.roll_continuation({'NextMode':'root','FreeSpinsLeft':0},s))
  self.assertTrue(contracts.roll_continuation({'Mode':'freespins','NextMode':'freespinsRespins','FreeSpinsLeft':10},s))
 def test_first_wheel_roll_differs_from_optional_later_skip(self):
  s=(ROOT/'private/references/rich-leprechaun-megaways/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'rootCascade','NextMode':'freespins_alternative','waitForAcceptWin':False},s))
  self.assertFalse(contracts.roll_continuation({'Mode':'freespins_alternative','NextMode':'freespins_alternative','waitForAcceptWin':False},s))
 def test_offered_native_credit_uses_accept_win_without_gamble(self):
  s=(ROOT/'private/references/book-of-games-20/client.js').read_text(encoding='utf-8')
  self.assertEqual(contracts.next_action({'NextMode':'root','FreeSpinsLeft':0,'waitForAcceptWin':True},s),'_AcceptWin')
 def test_old_official_client_declares_its_own_service(self):
  for file,code in [('book-of-games/legacy-client.js','bookofgames'),('monster-sushi/client.js','monstersushi')]:
   x=contracts.identify((ROOT/'private/references'/file).read_text(encoding='utf-8'))
   self.assertEqual(x['slotcode'],code);self.assertEqual(x['service_base'],'https://expo.bossgs.net/service')
 def test_legacy_sky_automatic_respin_groups_and_no_gamble_flag(self):
  s=(ROOT/'private/references/sky-lanterns/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'root','NextMode':'respin','FreeSpinsLeft':0},s))
  self.assertFalse(contracts.roll_continuation({'Mode':'root','NextMode':'unknown'},s))
 def test_legacy_angels_parser_marks_respin_and_fs_as_zero_debit_rolls(self):
  s=(ROOT/'private/references/angels-vs-demons/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'root','NextMode':'rootRespin'},s))
  self.assertTrue(contracts.roll_continuation({'Mode':'rootRespin','NextMode':'angelFS'},s))
  self.assertFalse(contracts.roll_continuation({'Mode':'root','NextMode':'unknown'},s))
 def test_legacy_buy_bodies_are_identified_without_inventing_parameters(self):
  book=contracts.identify((ROOT/'private/references/book-of-treasures/client.js').read_text(encoding='utf-8'))
  santa=contracts.identify((ROOT/'private/references/santa-vs-krampus/client.js').read_text(encoding='utf-8'))
  self.assertTrue(book['buy_bonus_contract']);self.assertFalse(book['buy_lines'])
  self.assertTrue(santa['buy_bonus_contract']);self.assertTrue(santa['buy_lines'])
 def test_indian_choice_uses_only_visible_unopened_native_board(self):
  s=(ROOT/'private/references/indian-call/client.js').read_text(encoding='utf-8')
  self.assertEqual(contracts.bonus_choice({'Mode':'root','NextMode':'bonus'},s),{'X':0,'Y':0})
  board=[[None]*5 for _ in range(4)];board[0][0]='B1'
  self.assertEqual(contracts.bonus_choice({'Mode':'bonus','NextMode':'bonus','Screen':board},s),{'X':1,'Y':0})
  self.assertIsNone(contracts.bonus_choice({'Mode':'bonus','NextMode':'bonus','Screen':[['B1']*5 for _ in range(4)]},s))
  delta=[[None]*5 for _ in range(4)];delta[0][1]='R4|10'
  self.assertEqual(contracts.bonus_choice({'Mode':'bonus','NextMode':'bonus','Screen':delta},s,opened=[{'X':0,'Y':0},{'X':1,'Y':0}]),{'X':2,'Y':0})
 def test_fortune_jaguar_uses_explicit_native_state_alias(self):
  s=(ROOT/'private/references/fortune-jaguar/client.js').read_text(encoding='utf-8')
  self.assertTrue(contracts.roll_continuation({'Mode':'root','NextMode':'respin_bonus','waitForAcceptWin':False},s))
 def test_legacy_book_declares_zero_charge_fs_and_respin(self):
  s=(ROOT/'private/references/book-of-treasures/client.js').read_text(encoding='utf-8')
  for mode in ['root_respin','fs','fs_respin']:
   self.assertTrue(contracts.roll_continuation({'Mode':'root','NextMode':mode},s))
  self.assertFalse(contracts.roll_continuation({'NextMode':'unknown'},s))
 def test_gamble_requires_offer_and_exact_native_red_contract(self):
  s=(ROOT/'private/references/book-of-games-20/client.js').read_text(encoding='utf-8')
  self.assertEqual(contracts.gamble_action({'NextMode':'root','FreeSpinsLeft':0,'waitForAcceptWin':True,'roundWin':20},s),{'data':0})
  self.assertIsNone(contracts.gamble_action({'NextMode':'root','FreeSpinsLeft':0,'waitForAcceptWin':False,'roundWin':20},s))
