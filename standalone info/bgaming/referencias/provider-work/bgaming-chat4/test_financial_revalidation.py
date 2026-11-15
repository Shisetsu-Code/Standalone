import unittest,json,tempfile
from pathlib import Path
from run_demo_qa import Demo
class RevalidationIsolation(unittest.TestCase):
 def test_publication_requires_all_modes_and_independent_native_success(self):
  from publish_financial_revalidation import validate_fresh
  root=Path(__file__).resolve().parent
  r=json.loads((root/'live/fresh-financial-revalidation/TheGodfather3PillarsOfPower.json').read_text());old=json.loads((root/r['historical_report_archive']).read_text())
  self.assertEqual(validate_fresh(r,old)['failed'],0)
  r['modes'].pop()
  with self.assertRaises(ValueError):validate_fresh(r,old)
 def test_publication_rejects_native_balance_tampering(self):
  from publish_financial_revalidation import validate_fresh
  root=Path(__file__).resolve().parent
  r=json.loads((root/'live/fresh-financial-revalidation/TheGodfather3PillarsOfPower.json').read_text());old=json.loads((root/r['historical_report_archive']).read_text());r['events'][-1]['response']['result']['balance']+=1
  with self.assertRaises(ValueError):validate_fresh(r,old)
 def test_fresh_native_debit_is_verified_without_canonical_session_write(self):
  from revalidate_financial_slots import FreshSlot
  from unittest.mock import patch
  d=FreshSlot({'game_id':'LuckyDragonMultiDiceX'},Path('synthetic-private.json'));d.active_mode={'cost_native':10};d.last_response={'balance':{'wallet':100000,'game':0},'flow':{'state':'ready','available_actions':['spin']}}
  response={'balance':{'wallet':99990,'game':0},'flow':{'state':'closed','available_actions':['spin']}}
  def received(self,command,options):self.events.append({'request':{'command':command,'options':options},'response':response,'status':200});self.last_response=response;return response
  with patch.object(Demo,'call',received):d.call('spin',{'bet':10})
  self.assertTrue(d.money_checks[0]['ok']);self.assertEqual(d.money_checks[0]['cost_native'],10)
 def test_native_checkpoint_uses_explicit_private_destination(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='revalidation-test-') as directory:
   d=Demo({'game_id':'DigDigDigger'});d.private_session_path=Path(directory)/'session.json';d.api='https://demo.bgaming-network.com/api';d.page='https://demo.bgaming-network.com/';d.csrf_name='X-CSRF';d.csrf_value='synthetic-test';d.checkpoint({'status':'received'})
   self.assertEqual(json.loads(d.private_session_path.read_text())['game_id'],'DigDigDigger')
 def test_rpc_checkpoint_is_separate_from_canonical_private_context(self):
  from hyperhive_adapter import Hyperhive
  d=Demo({'game_id':'TheGodfather3PillarsOfPower'});d.page='https://qa.demo.bgaming-network.com/hyperhive';d.private_session_path=Path('isolated-synthetic-session.json');h=Hyperhive(d,{'play_token':'synthetic-test'})
  self.assertEqual(h.private,d.private_session_path)
