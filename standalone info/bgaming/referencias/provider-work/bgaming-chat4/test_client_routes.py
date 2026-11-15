import unittest
from legacy_metadata import client_route
class ClientRoutes(unittest.TestCase):
 def test_basic_mapping_takes_priority_over_flat_fallback(self):
  loader='window.SKIN_DIRS={"xmas":{root:"xmas",res:"xmas/v1"},"basic":{root:"basic",res:"basic/v1"}};var {root:a,res:b="v1"}=i[n]||i.basic||{};';self.assertEqual(client_route(loader),('basic/v1','basic/v1/bundle.js'))
 def test_flat_and_module_routes(self):
  self.assertEqual(client_route('var {res:t="v0.0.59_0c658e7"}=x'),('v0.0.59_0c658e7','v0.0.59_0c658e7/bundle.js'));self.assertEqual(client_route('script.src=path+"/assets/index-hash.js"'),('index-hash.js','assets/index-hash.js'))
 def test_source_route_cannot_escape_private_research_folder(self):
  with self.assertRaises(ValueError):client_route('window.SKIN_DIRS={"basic":{res:"../../outside"}}')
if __name__=='__main__':unittest.main()
