import unittest,importlib.util
class ParallelTests(unittest.TestCase):
    def test_never_launch_closed_or_adopted_games(self):
        self.assertIsNotNone(importlib.util.find_spec('run_ruby_parallel'),'Parallel coordinator missing')
        from run_ruby_parallel import launch_candidates
        self.assertEqual(launch_candidates({'a':'purchase_verified','b':'active','c':'pending','d':'needs_review'}),['c'])
if __name__=='__main__':unittest.main()
