import unittest
from pathlib import Path
from checkpoint_guard import acquire,require_inactive
P=Path(__file__).parent
class CheckpointGuard(unittest.TestCase):
 def test_interrupted_game_cannot_be_blindly_replaced(self):
  with self.assertRaises(RuntimeError):require_inactive({'active_game':'PendingDemo','results':{}})
  require_inactive({'active_game':None,'results':{}})
 def test_second_runner_excluded_and_lock_released_on_close(self):
  path=P/'test-runner-exclusion.lock';first=acquire(path)
  try:
   with self.assertRaises(RuntimeError):acquire(path)
  finally:first.close()
  second=acquire(path);second.close()
 def test_stopped_selection_is_not_marked_as_finished(self):
  from run_demo_qa import record_queue_end
  state={'results':{'A':{}},'queue_pass_finished_at':'old'};record_queue_end(state,[{'game_id':'A'},{'game_id':'B'}]);self.assertNotIn('queue_pass_finished_at',state);self.assertEqual(state['selected_queue_remaining'],1)
  state['results']['B']={};record_queue_end(state,[{'game_id':'A'},{'game_id':'B'}]);self.assertIn('queue_pass_finished_at',state);self.assertNotIn('queue_paused_at',state)
if __name__=='__main__':unittest.main()
