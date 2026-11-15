import unittest
from unittest.mock import patch
from run_demo_qa import Demo
class Preselection(unittest.TestCase):
 def state(self):return {'balance':{'wallet':99190,'game':0},'flow':{'state':'preselection_game','available_actions':['init','preselection_game']}}
 def test_source_verified_command_resumes_without_new_spin(self):
  d=Demo({'game_id':'AlwaysUp'});calls=[]
  def call(command,options=None):calls.append((command,options));return {'balance':{'wallet':99190,'game':500},'flow':{'state':'closed','available_actions':['init','spin']}}
  d.call=call
  with patch('legacy_metadata.prove_continuations',return_value={'legacy_continuations':['preselection_game']}):d.settle(self.state())
  self.assertEqual(calls,[('preselection_game',None)])
 def test_unproved_selection_is_not_guessed(self):
  d=Demo({'game_id':'Unknown'});d.call=lambda *a:self.fail('Unexpected request')
  with patch('legacy_metadata.prove_continuations',return_value={'legacy_continuations':[]}):
   with self.assertRaises(RuntimeError):d.settle(self.state())
 def test_source_verified_auto_door_selection_keeps_options(self):
  d=Demo({'game_id':'WildMoonThieves'});calls=[];state=self.state();state['flow']['available_actions']=['init','play_preselection_game']
  d.protocol_metadata={'legacy_continuations':['play_preselection_game'],'continuation_options':{'play_preselection_game':{'mode':'auto'}}}
  def call(command,options=None):calls.append((command,options));return {'balance':{'wallet':99190,'game':500},'flow':{'state':'closed'}}
  d.call=call;d.settle(state);self.assertEqual(calls,[('play_preselection_game',{'mode':'auto'})])
if __name__=='__main__':unittest.main()
