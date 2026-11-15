import unittest,importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('adaptive_rate',Path(__file__).with_name('adaptive_rate.py'))
rate=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists():spec.loader.exec_module(rate)

class AdaptiveRateTests(unittest.TestCase):
    def test_successes_reduce_interval_gradually_to_floor(self):
        update=getattr(rate,'feedback',lambda p,outcome,**kw:p)
        policy={'interval':20,'successes':0,'floor':10}
        for _ in range(10):policy=update(policy,'success',now=100)
        self.assertEqual(policy['interval'],10)

    def test_rejection_honors_retry_after_and_increases_pause(self):
        update=getattr(rate,'feedback',lambda p,outcome,**kw:p)
        p=update({'interval':20,'successes':3,'floor':10},'rate_limited',retry_after=180,now=100)
        self.assertEqual(p['interval'],40)
        self.assertEqual(p['cooldown_until'],280)
        self.assertEqual(p['successes'],0)

    def test_protocol_unknown_does_not_misidentify_rate_limiting(self):
        update=getattr(rate,'feedback',lambda p,outcome,**kw:{'interval':999})
        self.assertEqual(update({'interval':20},'unknown_protocol',now=100)['interval'],20)

if __name__=='__main__':unittest.main()
