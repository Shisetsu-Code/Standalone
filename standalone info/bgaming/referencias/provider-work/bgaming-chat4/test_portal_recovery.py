import unittest
from unittest.mock import patch
from run_demo_qa import Demo
from analyze import Sanitizer
from resume_frenzy import restore_aliases
class PortalRecovery(unittest.TestCase):
 def test_pending_portal_is_not_another_spin(self):
  d=Demo({'game_id':'FrenzyClusters'});d.active_mode={'selected_portal':4};calls=[]
  pending={'flow':{'state':'gamble_bonus','available_actions':['init','gamble_bonus']},'balance':{'wallet':100,'game':0}}
  closed={'flow':{'state':'closed','available_actions':['init','spin']},'balance':{'wallet':100,'game':0}}
  d.call=lambda cmd,options:(calls.append((cmd,options)) or closed)
  with patch('run_demo_qa.time.sleep',return_value=None):self.assertEqual(d.settle(pending),closed)
  self.assertEqual(calls,[('gamble_bonus',{'selected_portal':4})])
 def test_portal_outside_verified_range_rejected(self):
  d=Demo({'game_id':'FrenzyClusters'});d.active_mode={'selected_portal':5};d.call=lambda *a:self.fail('Out-of-range choice must not be sent')
  with self.assertRaises(RuntimeError):d.settle({'flow':{'state':'gamble_bonus','available_actions':['init','gamble_bonus']},'balance':{'wallet':100,'game':0}})
 def test_aliases_remain_continuous_when_resuming(self):
  s=Sanitizer();events=[{'request':{'extra_data':{'round_series_id':'round_series_id-1'}},'response':{'flow':{'round_id':'round_id-2','last_action_id':'last_action_id-2'}}}]
  restore_aliases(s,events,{'flow':{'round_id':9999,'last_action_id':'native-action-2'}},123456789)
  self.assertEqual(s.clean({'round_id':9999})['round_id'],'round_id-2');self.assertEqual(s.clean({'round_id':10000})['round_id'],'round_id-3');self.assertEqual(s.clean({'last_action_id':'native-action-3'})['last_action_id'],'last_action_id-3')
if __name__=='__main__':unittest.main()
