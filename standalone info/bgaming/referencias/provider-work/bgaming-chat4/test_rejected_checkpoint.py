import unittest
from legacy_recovery import rejection_request_matches
class RejectedCheckpoint(unittest.TestCase):
 def test_old_rejection_requires_matching_command_and_http_status(self):
  e={'status':422,'request':{'command':'play_bonus'}}
  d={'operation':{'status':'http_rejection','command':'play_bonus','http_status':422}}
  self.assertTrue(rejection_request_matches(d,e,lambda x:x))
  d['operation']['command']='spin';self.assertFalse(rejection_request_matches(d,e,lambda x:x))
  d['operation']['command']='play_bonus';d['operation'].pop('http_status');self.assertFalse(rejection_request_matches(d,e,lambda x:x))
 def test_modern_record_does_not_fall_back_after_request_mismatch(self):
  e={'status':422,'request':{'command':'play_bonus'}}
  d={'operation':{'status':'http_rejection','command':'play_bonus','http_status':422},'last_request':{'command':'spin'}}
  self.assertFalse(rejection_request_matches(d,e,lambda x:x))
