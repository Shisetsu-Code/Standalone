import json,unittest
from pathlib import Path
from alice_choices import next_action,expand
P=Path(__file__).parent
class AliceChoices(unittest.TestCase):
 def meta(self):return json.loads((P/'protocols/AliceWonderLuck.choices.json').read_text(encoding='utf8'))
 def test_all_policies_keep_native_bets_and_prices(self):
  modes=expand([{'name':'freespin_buy:0','options':{'bet':20,'purchased_feature':'freespin_buy','purchased_feature_level':'0'},'cost_native':2000}],self.meta());self.assertEqual(len(modes),5);self.assertEqual({m['cost_native'] for m in modes},{2000});self.assertTrue(all(m['options']['bet']==20 for m in modes))
 def test_gamble_once_then_collect(self):
  r={'flow':{'state':'gamble_bonus','available_actions':['init','gamble_bonus','pick_cards']}};mode={'alice_gamble_policy':'gamble_once'};progress={};self.assertEqual(next_action(r,mode,progress,self.meta())['command'],'gamble_bonus');self.assertEqual(next_action(r,mode,progress,self.meta()),{'command':'pick_cards','options':{'mode':'select_pick_cards'}})
 def test_manual_boundaries_and_no_duplicate_selection(self):
  r={'flow':{'state':'pick_cards','available_actions':['init','pick_cards']}};meta=self.meta();self.assertEqual(meta['card_count'],16)
  for policy,expected in [('manual_low',[0,1]),('manual_high',[15,14])]:
   progress={};actual=[next_action(r,{'alice_card_policy':policy},progress,meta)['options']['index'] for _ in range(2)];self.assertEqual(actual,expected)
 def test_command_must_be_advertised(self):
  with self.assertRaises(RuntimeError):next_action({'flow':{'state':'gamble_bonus','available_actions':['init']}},{},{},self.meta())
 def test_full_native_init_expands_both_purchase_levels(self):
  from run_demo_qa import modes_from_init
  report=json.loads((P/'live/AliceWonderLuck.json').read_text(encoding='utf8'));modes=modes_from_init(report['events'][0]['response'],self.meta());self.assertEqual(len(modes),12);self.assertEqual({m['cost_native'] for m in modes},{20,100,2000,5000})
if __name__=='__main__':unittest.main()
