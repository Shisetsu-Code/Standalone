import unittest
from freespin_types import metadata,expand
class FreeSpinTypes(unittest.TestCase):
 def test_two_source_choices_keep_native_purchase_and_options(self):
  source='nl="giant_symbol",al="high_symbols";this.additionalSpinOptions.freespins_type=3===this.freespinsReelsCount?nl:al;delete this.additionalSpinOptions.freespins_type;'
  meta=metadata(source);self.assertEqual(meta['freespin_types'],['giant_symbol','high_symbols'])
  modes=expand([{'name':'normal','options':{'bet':25},'cost_native':25},{'name':'freespin_buy','options':{'bet':25,'purchased_feature':'freespin_buy'},'cost_native':1000}],meta)
  self.assertEqual(len(modes),3);self.assertEqual([m['freespin_options'] for m in modes[1:]],[{'freespins_type':'giant_symbol'},{'freespins_type':'high_symbols'}]);self.assertEqual(modes[1]['options'],modes[2]['options'])
 def test_one_source_type_not_mistaken_for_two_ui_labels(self):
  source='Ho="high_symbols";this.additionalSpinOptions.freespins_type=Ho;delete this.additionalSpinOptions.freespins_type;'
  self.assertEqual(metadata(source)['freespin_types'],['high_symbols'])
 def test_unknown_source_choice_not_guessed(self):
  with self.assertRaises(ValueError):metadata('this.additionalSpinOptions.freespins_type=computeChoice();delete this.additionalSpinOptions.freespins_type;')
 def test_free_spin_selector_not_sent_to_unrelated_respin(self):
  from run_demo_qa import Demo
  d=Demo({'game_id':'MonsterHunt'});d.active_mode={'freespin_options':{'freespins_type':'high_symbols'}}
  self.assertEqual(d.continuation_options('freespin'),{'freespins_type':'high_symbols'});self.assertIsNone(d.continuation_options('respin'))
 def test_native_response_must_confirm_selected_type(self):
  from run_demo_qa import Demo
  d=Demo({'game_id':'MonsterHunt'});d.active_mode={'freespin_options':{'freespins_type':'high_symbols'}};calls=[]
  def call(command,options):calls.append((command,options));d.events.append({});return {'features':{'freespins_type':'high_symbols'},'balance':{'wallet':100000,'game':20},'flow':{'state':'closed'}}
  d.call=call;r=d.settle({'balance':{'wallet':100000,'game':0},'flow':{'state':'freespins','available_actions':['init','freespin']}});self.assertEqual(calls,[('freespin',{'freespins_type':'high_symbols'})]);self.assertTrue(d.freespin_type_confirmed)
