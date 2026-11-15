import unittest
from types import SimpleNamespace
from run_demo_qa import retain_launch_evidence
class BootstrapRetention(unittest.TestCase):
 def test_resource_failure_keeps_safe_launch_evidence_without_private_urls(self):
  demo=SimpleNamespace(bootstrap={'identifier':'Test','currency':'FUN','server_id':'demo'},api='private-api',page='private-page',protocol_metadata={});report={'status':'needs_review'};retain_launch_evidence(report,demo);self.assertEqual(report['bootstrap']['identifier'],'Test');self.assertEqual(report['protocol'],'legacy');self.assertNotIn('api',report);self.assertNotIn('page',report)
 def test_failure_before_validated_launch_is_not_labelled_legacy(self):
  report={};retain_launch_evidence(report,SimpleNamespace());self.assertEqual(report['protocol'],'unknown');self.assertNotIn('bootstrap',report)
