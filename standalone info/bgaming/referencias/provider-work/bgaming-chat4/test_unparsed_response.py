import unittest
from types import SimpleNamespace
from unittest.mock import patch
from run_demo_qa import Demo
class UnparsedResponse(unittest.TestCase):
 def test_receipt_preserved_without_repeating_post(self):
  class Received:
   status=200
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return b'<html>synthetic-private-body</html>'
  d=Demo({'game_id':'Synthetic'});d.api='https://demo.bgaming-network.com/api';d.page=d.api;d.csrf_name='X-Test';d.csrf_value='synthetic';calls=[];checkpoints=[];d.checkpoint=lambda operation:checkpoints.append(operation);d.opener=SimpleNamespace(open=lambda *a,**k:(calls.append(1) or Received()))
  with patch('pathlib.Path.write_bytes') as write:
   with self.assertRaises(RuntimeError):d.call('spin',{'bet':10})
  self.assertEqual(len(calls),1);write.assert_called_once_with(b'<html>synthetic-private-body</html>');self.assertEqual(checkpoints[-1]['status'],'received_unparsed');self.assertEqual(d.events[-1]['response']['body_format'],'non_json');self.assertNotIn('synthetic-private-body',str(d.events))
if __name__=='__main__':unittest.main()
