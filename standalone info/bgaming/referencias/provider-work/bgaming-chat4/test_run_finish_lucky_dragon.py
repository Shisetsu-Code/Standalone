import copy,json
from pathlib import Path
import tempfile,unittest
from types import SimpleNamespace
import test_finish_lucky_dragon_controls as fixtures
from unittest.mock import patch
import run_finish_lucky_dragon as cli

class RunLuckyDragon(unittest.TestCase):
 def setUp(self):
  # Exercise persistence content in temporary roots without testing the
  # shared Windows atomic-replace implementation used by the live runner.
  def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf8')
  replacement=patch.object(cli,'save',save);replacement.start();self.addCleanup(replacement.stop)
 def setup_paths(self,base):
  root=Path(base)/'public';private=Path(base)/'private';(root/'live').mkdir(parents=True);private.mkdir()
  report=fixtures.FinishLuckyDragon().report();raw={'fresh_demo':True,'game_id':cli.GID,'operation':{'status':'received'},'last_response':copy.deepcopy(report['events'][-1]['response']),'last_request':copy.deepcopy(report['events'][-1]['request']),'public_events':copy.deepcopy(report['events']),'api':'https://demo.bgaming-network.com/api/private-old','csrf_value':'private-old-secret','cookies':[{'value':'private-old-cookie'}]}
  (root/'live'/f'{cli.GID}.json').write_text(json.dumps(report));(private/f'{cli.GID}.session.json').write_text(json.dumps(raw));(root/'STOP').write_text('CHECKPOINT_MAINTENANCE');(root/'run-state.json').write_text(json.dumps({'active_game':None,'last_launch_epoch':1000,'results':{}}))
  return root,private,report,raw
 def test_archives_precede_fresh_launch_and_final_state_preserves_false_check(self):
  with tempfile.TemporaryDirectory() as base:
   root,private,report,raw=self.setup_paths(base);output=[];demos=[]
   def factory(game):
    demo=SimpleNamespace(game=game,events=[],money_checks=[],protocol_metadata={},bootstrap={'identifier':cli.GID,'currency':'FUN','server_id':'demo'})
    def launch():
     self.assertEqual(json.loads((private/'attempts'/f'{cli.GID}.before-finish-ui-controls.session.json').read_text()),raw)
     self.assertTrue((root/'live/attempts'/f'{cli.GID}.before-finish-ui-controls.json').exists())
     from checkpoint_guard import acquire
     with self.assertRaises(RuntimeError):acquire(root/'runner.lock')
     initial=copy.deepcopy(report['events'][0]['response']);demo.events.append({'request':{'command':'init'},'response':initial});return initial
    demo.launch=launch;demos.append(demo);return demo
   def finish(report_arg,**kwargs):
    self.assertEqual(kwargs['old_private_context'],raw)
    kwargs['private_checkpoint']('historical_context_preserved',{'report':report_arg,'private_context':raw})
    kwargs['private_checkpoint']('before_independent_official_FUN_launch',{'last_launch_epoch':1060})
    demo,initial=kwargs['fresh_launch']()
    result=copy.deepcopy(report_arg);result['modes'].append({'status':'closed','financial_verified':False});result['status']='needs_review'
    return result
   status=cli.run(root=root,private=private,demo_factory=factory,finish_fn=finish,output=lambda value:output.append(value))
   final=json.loads((root/'live'/f'{cli.GID}.json').read_text());state=json.loads((root/'run-state.json').read_text())
   self.assertEqual(status,'needs_review');self.assertEqual(final['checks'],report['checks']);self.assertIsNone(state['active_game']);self.assertEqual(state['last_launch_epoch'],1060)
   self.assertEqual((root/'STOP').read_text(),'CHECKPOINT_MAINTENANCE');self.assertNotIn('secret',' '.join(output))
   with self.assertRaises(ValueError):cli.run(root=root,private=private,demo_factory=factory,finish_fn=finish,output=lambda value:None)
   self.assertEqual(len(demos),1)
 def test_active_queue_or_wrong_stop_never_archives_or_launches(self):
  for active,stop in [('AllLuckyClover','CHECKPOINT_MAINTENANCE'),(None,'CONTINUE')]:
   with tempfile.TemporaryDirectory() as base:
    root,private,report,raw=self.setup_paths(base);state=json.loads((root/'run-state.json').read_text());state['active_game']=active;(root/'run-state.json').write_text(json.dumps(state));(root/'STOP').write_text(stop)
    with self.assertRaises((RuntimeError,ValueError)):cli.run(root=root,private=private,demo_factory=lambda *args:self.fail('Must not launch'),output=lambda value:None)
    self.assertFalse((private/'lucky-dragon-finish-controls/attempt.json').exists())
 def test_error_retains_new_received_events_and_old_check_without_replay(self):
  with tempfile.TemporaryDirectory() as base:
   root,private,report,raw=self.setup_paths(base)
   def factory(game):
    demo=SimpleNamespace(game=game,events=[],money_checks=[],protocol_metadata={})
    def launch():
     initial=copy.deepcopy(report['events'][0]['response']);demo.events.append({'request':{'command':'init'},'response':initial});return initial
    demo.launch=launch;return demo
   def finish(report_arg,**kwargs):
    kwargs['private_checkpoint']('historical_context_preserved',{'report':report_arg,'private_context':raw});kwargs['private_checkpoint']('before_independent_official_FUN_launch',{'last_launch_epoch':1060})
    demo,initial=kwargs['fresh_launch']();demo.events.append({'request':{'command':'spin','options':{'bet':10,'purchased_feature':'bonus_buy_1_chance'}},'response':{'balance':{'wallet':99000,'game':0},'flow':{'state':'closed'}}});demo.money_checks.append({'kind':'receipt','ok':False})
    raise RuntimeError('actual receipt differs')
   self.assertEqual(cli.run(root=root,private=private,demo_factory=factory,finish_fn=finish,output=lambda value:None),'needs_review')
   final=json.loads((root/'live'/f'{cli.GID}.json').read_text());self.assertEqual(len(final['events']),6);self.assertEqual(final['events'][-1]['event_alias_id'],'fresh_control1:1');self.assertFalse(final['checks'][1]['ok']);self.assertIsNone(json.loads((root/'run-state.json').read_text())['active_game'])
 def test_real_pure_helper_integrates_with_cli_using_only_offline_transport(self):
  with tempfile.TemporaryDirectory() as base:
   root,private,report,raw=self.setup_paths(base);calls=[]
   def factory(game):
    initial=copy.deepcopy(report['events'][0]['response'])
    demo=SimpleNamespace(game=game,bootstrap={'identifier':cli.GID,'currency':'FUN','server_id':'demo'},events=[],money_checks=[],protocol_metadata={},prev=None,last_response=None)
    def launch():demo.events.append({'request':{'command':'init'},'response':copy.deepcopy(initial)});demo.last_response=initial;return initial
    def call(command,options=None):
     calls.append((command,copy.deepcopy(options)))
     response={'api_version':'2','outcome':{'bet':10,'win':0},'balance':{'wallet':99000,'game':0},'flow':{'state':'closed','available_actions':['init','spin'],'purchased_feature':{'name':'bonus_buy','level':'bonus_buy_1'}}}
     demo.events.append({'request':{'command':command,'options':copy.deepcopy(options)},'response':response});demo.last_response=response;return response
    demo.launch=launch;demo.call=call;return demo
   def fetch(url):return fixtures.LOADER.read_bytes() if url.endswith('loader.js') else fixtures.SOURCE.read_bytes()
   status=cli.run(root=root,private=private,demo_factory=factory,fetch_static=fetch,output=lambda value:None)
   final=json.loads((root/'live'/f'{cli.GID}.json').read_text());state=json.loads((root/'run-state.json').read_text())
   self.assertEqual(status,'needs_review');self.assertEqual(calls,[('spin',{'bet':10,'purchased_feature':'bonus_buy_1_chance'})]);self.assertEqual(len(final['modes']),3)
   self.assertFalse(final['checks'][1]['ok']);self.assertFalse(final['modes'][1]['financial_verified']);self.assertTrue(final['modes'][2]['financial_verified'])
   self.assertEqual(final['protocol_metadata'],report['protocol_metadata']);self.assertEqual(state['results'][cli.GID]['financial_unverified_modes'],1)
