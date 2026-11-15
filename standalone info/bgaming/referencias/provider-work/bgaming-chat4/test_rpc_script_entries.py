import unittest
from hyperhive_adapter import native_script_entries
class ScriptEntries(unittest.TestCase):
 def test_cache_hash_query_is_preserved(self):
  s='<script src="main.js?6a62dcd38d7dd15080bb"></script><script src="./bundle.js?v=1.2.3"></script>'
  self.assertEqual(native_script_entries(s),['main.js?6a62dcd38d7dd15080bb','./bundle.js?v=1.2.3'])
 def test_external_traversal_or_auth_query_not_a_local_entry(self):
  s=''.join('<script src="'+x+'"></script>' for x in ['https://other.example/main.js','../main.js','main.js?token=private','main.js#fragment'])
  self.assertEqual(native_script_entries(s),[])
