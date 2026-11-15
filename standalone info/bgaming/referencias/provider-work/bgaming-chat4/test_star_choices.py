import unittest,json
from pathlib import Path
from star_choices import next_request,expand
P=Path(__file__).parent
class StarChoices(unittest.TestCase):
 def test_captured_paid_trigger_requests_choice_not_another_spin(self):
  r=json.loads((P/'StarTrekNextGen.trigger.reference.json').read_text(encoding='utf8'))['response']['result'];q=next_request(r,{'bet_native':20,'freespin_choice':1},{'star_choices_verified':True});self.assertEqual(q['custom_req'],{'action':'fs_choice','choice':1,'exponent':2});self.assertNotIn('purchased_feature',q)
 def test_all_four_choices_expand_only_freespin_purchase(self):
  modes=[{'name':'normal','custom_params':{}},{'name':'buy','custom_params':{'isFeatureBuyFreeSpin':True}},{'name':'respin','custom_params':{'isFeatureBuyRespin':True}}];modes=expand(modes);self.assertEqual(len(modes),6);self.assertEqual([m['freespin_choice'] for m in modes if 'freespin_choice' in m],[1,2,3,4])
 def test_active_free_spins_use_free_action(self):
  r={'final':False,'resp':{'engine':{'gamestate':{'action':'fs_choice','freespinState':{'numFreeSpins':6}}}}};self.assertEqual(next_request(r,{'bet_native':20},{'star_choices_verified':True})['custom_req']['action'],'freespin')
 def test_unknown_state_and_unverified_choice_rejected(self):
  r={'final':False,'resp':{'engine':{'gamestate':{'action':'mystery'}}}}
  with self.assertRaises(RuntimeError):next_request(r,{'bet_native':20},{'star_choices_verified':True})
  with self.assertRaises(RuntimeError):next_request(r,{'bet_native':20},{})
 def test_pick_and_cash_use_source_command_without_invented_input(self):
  r={'final':False,'resp':{'engine':{'gamestate':{'action':'respin','respinState':{'numOfRespin':2,'revealOrder':{'total_pick':3}}}}}};q=next_request(r,{'bet_native':20},{'star_choices_verified':True});self.assertEqual(q['custom_req'],{'action':'pick_respin','exponent':2})
