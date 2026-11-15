import json,unittest,copy
from types import SimpleNamespace
from unittest.mock import patch
from analyze import Sanitizer
from legacy_recovery import adopt_observed_init
class InitRefresh(unittest.TestCase):
 def fixture(self):
  old={'balance':{'wallet':98380,'game':0},'flow':{'round_id':'r0','state':'preselection_game'}};response={'balance':{'wallet':100000,'game':0},'flow':{'round_id':'r0','state':'preselection_game'},'options':{'currency':{'code':'FUN','subunits':100}}};rb={'status':200,'time':'2026-10-29T10:00:00','request':{'command':'init','extra_data':{'round_series_id':123}},'response':response,'response_sha256':'synthetic-fixture'}
  events=[{'time':'2026-10-29T09:00:00','response':copy.deepcopy(old)}];demo=SimpleNamespace(last_response=copy.deepcopy(old),series=123,events=events,clean=Sanitizer());return demo,{'events':events},rb
 def test_provider_refresh_is_preserved_separately_not_rewritten_as_win(self):
  demo,report,rb=self.fixture()
  with patch('pathlib.Path.read_text',return_value=json.dumps(rb)):response=adopt_observed_init(demo,report,'Synthetic')
  self.assertEqual(response['balance']['wallet'],100000);self.assertEqual(report['events'][0]['response']['balance']['wallet'],98380);self.assertEqual(report['provider_state_observations'][0]['kind'],'native_init_balance_refresh');self.assertNotIn('win',report['events'][-1]['response']);self.assertEqual(report['events'][-1]['request']['command'],'init')
 def test_different_round_does_not_resume_the_old_bonus(self):
  demo,report,rb=self.fixture();rb['response']['flow']['round_id']='different'
  with patch('pathlib.Path.read_text',return_value=json.dumps(rb)):
   with self.assertRaises(RuntimeError):adopt_observed_init(demo,report,'Synthetic')
  self.assertEqual(len(report['events']),1)
if __name__=='__main__':unittest.main()
