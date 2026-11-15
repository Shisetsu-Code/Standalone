import copy,json
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from all_lucky_variants import VariantGate
import finish_lucky_dragon_controls as x

ROOT=Path(__file__).resolve().parents[2]
PUBLIC=Path(__file__).resolve().parent
SOURCE=ROOT/'bgaming-private-chat4/research/legacy/LuckyDragonMultiDiceX/v0.0.101_v14.19.2/bundle.js'
LOADER=ROOT/'bgaming-private-chat4/research/legacy/LuckyDragonMultiDiceX/loader.js'

class FinishLuckyDragon(unittest.TestCase):
 def report(self):
  # Offline fixture of the four observed contracts. Do not couple tests to
  # the live report that the parent will later extend with a fresh session.
  initial={'api_version':'2','options':{'available_bets':[10,20],'currency':{'code':'FUN','symbol':'FUN','subunits':100},'feature_options':{'feature_multipliers':{'base_bet':10,'bonus_buy':{'bonus_buy_0':300,'bonus_buy_1':1000},'bonus_buy_0_chance':300,'bonus_buy_1_chance':1000},'disabled_features':[]}},'balance':{'wallet':100000,'game':0},'flow':{'state':'ready','available_actions':['init','spin']}}
  def response(wallet,game,receipt):return {'api_version':'2','outcome':{'bet':10,'win':game},'balance':{'wallet':wallet,'game':game},'flow':{'state':'closed','available_actions':['init','spin'],'purchased_feature':receipt}}
  normal={'name':'normal','command':'spin','options':{'bet':10},'cost_native':10}
  events=[{'status':200,'request':{'command':'init'},'response':initial},{'status':200,'request':{'command':'spin','options':{'bet':10}},'response':response(99990,30,{})},{'status':422,'request':{'command':'spin','options':{'bet':10,'purchased_feature':'bonus_buy','purchased_feature_level':'bonus_buy_0'}},'response':{'errors':[{'code':203,'desc':'invalid_options'}]}},{'status':200,'request':{'command':'spin','options':{'bet':10,'purchased_feature':'bonus_buy_0_chance'}},'response':response(99700,60,{'name':'bonus_buy','level':'bonus_buy_0'})}]
  return {'game':{'game_id':x.GID,'demo_url':'https://demo.bgaming-network.com/play/'+x.GID+'/FUN?server=demo'},'events':events,'checks':[{'expected':99990,'actual':99990,'ok':True},{'expected':99720,'actual':99700,'ok':False}],'modes':[{'mode':normal,'status':'closed','first_event':1,'last_event':1}],'protocol_metadata':{'source_sha256':x.SOURCE_SHA256,'prior_metadata_retained':True},'status':'needs_review'}
 def test_received_first_control_is_closed_without_financial_reclassification(self):
  original=self.report();before=copy.deepcopy(original);derived=x.normalize_received(original,SOURCE.read_bytes())
  self.assertEqual(original,before);self.assertEqual(derived['events'],original['events'])
  self.assertEqual(derived['checks'],original['checks']);self.assertFalse(derived['checks'][-1]['ok'])
  mode=derived['modes'][-1]
  self.assertEqual(mode['mode']['name'],'bonus_buy_0_chance');self.assertEqual(mode['status'],'closed');self.assertFalse(mode['financial_verified'])
  self.assertEqual(mode['first_event'],3);self.assertEqual(derived['protocol_metadata'],original['protocol_metadata'])
 def harness(self,root,*,fresh_wallet=70000,wrong_receipt=False):
  original=self.report();initial=copy.deepcopy(original['events'][0]['response']);initial['balance']={'wallet':fresh_wallet,'game':0}
  events=[{'request':{'command':'init'},'response':copy.deepcopy(initial)}];calls=[];private=[];clock={'time':1000}
  def sleep(seconds):clock['time']+=seconds
  gate=VariantGate(root,last_launch_epoch=1000,clock=lambda:clock['time'],sleeper=sleep)
  demo=SimpleNamespace(game=copy.deepcopy(original['game']),bootstrap={'identifier':'LuckyDragonMultiDiceX','currency':'FUN','server_id':'demo'},events=events,money_checks=[],prev=None,last_response=initial,protocol_metadata={})
  def call(command,options=None):
   calls.append((command,copy.deepcopy(options)))
   response={'api_version':'2','features':{'purchased':'bonus_buy'},'outcome':{'bet':10,'win':0},'balance':{'wallet':fresh_wallet-1000,'game':0},'flow':{'state':'closed','command':'spin','available_actions':['init','spin'],'purchased_feature':{'name':'bonus_buy','level':'bonus_buy_0' if wrong_receipt else 'bonus_buy_1'}}}
   demo.events.append({'request':{'command':command,'options':copy.deepcopy(options)},'response':response});demo.last_response=response;return response
  demo.call=call
  def launch():return demo,copy.deepcopy(initial)
  def source(url):return LOADER.read_bytes() if url.endswith('loader.js') else SOURCE.read_bytes()
  return original,gate,launch,source,calls,private,clock,demo
 def test_only_second_control_uses_fresh_native_baseline_and_separate_event_namespace(self):
  with tempfile.TemporaryDirectory() as root:
   original,gate,launch,source,calls,private,clock,demo=self.harness(root)
   before=copy.deepcopy(original)
   with gate:result=x.finish(original,gate=gate,fresh_launch=launch,fetch_source=source,private_checkpoint=lambda stage,data:private.append((stage,copy.deepcopy(data))))
   self.assertEqual(original,before)
   self.assertEqual(calls,[('spin',{'bet':10,'purchased_feature':'bonus_buy_1_chance'})])
   self.assertEqual(result['status'],'needs_review');self.assertFalse(result['checks'][1]['ok'])
   paid=[c for c in result['checks'] if c.get('kind')=='lucky_dragon_fresh_native_debit'][0]
   self.assertEqual(paid['expected'],69000);self.assertTrue(paid['ok'])
   self.assertEqual(result['events'][0]['event_alias_id'],'historical:0');self.assertEqual(result['events'][4]['event_alias_id'],'fresh_control1:0')
   self.assertEqual(result['session_contexts'][1]['native_initial_balance'],{'wallet':70000,'game':0})
   self.assertTrue(result['modes'][-1]['financial_verified']);self.assertGreaterEqual(clock['time'],1060)
 def test_wrong_actual_receipt_fails_after_one_spin_without_retry(self):
  with tempfile.TemporaryDirectory() as root:
   original,gate,launch,source,calls,private,clock,demo=self.harness(root,wrong_receipt=True)
   with gate:
    with self.assertRaisesRegex(RuntimeError,'receipt'):x.finish(original,gate=gate,fresh_launch=launch,fetch_source=source,private_checkpoint=lambda *args:None)
   self.assertEqual(len(calls),1);self.assertTrue(any(c.get('kind')=='lucky_dragon_receipt' and not c['ok'] for c in demo.money_checks))
 def test_source_changed_stops_before_spin(self):
  with tempfile.TemporaryDirectory() as root:
   original,gate,launch,source,calls,private,clock,demo=self.harness(root)
   with gate:
    with self.assertRaises(ValueError):x.finish(original,gate=gate,fresh_launch=launch,fetch_source=lambda url:b'changed',private_checkpoint=lambda *args:None)
   self.assertFalse(calls)
 def test_historical_mutation_or_open_result_is_not_normalized(self):
  report=self.report();report['events'][3]['response']['flow']['state']='respin'
  with self.assertRaises(ValueError):x.normalize_received(report,SOURCE.read_bytes())
 def test_fresh_context_cannot_carry_old_previous_balance(self):
  with tempfile.TemporaryDirectory() as root:
   original,gate,launch,source,calls,private,clock,demo=self.harness(root);demo.prev=copy.deepcopy(original['events'][-1]['response'])
   with gate:
    with self.assertRaises(ValueError):x.finish(original,gate=gate,fresh_launch=launch,fetch_source=source,private_checkpoint=lambda *args:None)
   self.assertFalse(calls)
 def test_only_source_automatic_respin_continues_without_another_purchase(self):
  with tempfile.TemporaryDirectory() as root:
   original,gate,launch,source,calls,private,clock,demo=self.harness(root);original_call=demo.call
   def call(command,options=None):
    if command=='spin':
     response=original_call(command,options);response['flow']['state']='respin';response['flow']['available_actions']=['init','respin'];return response
    calls.append((command,options));response={'api_version':'2','outcome':{'win':200},'balance':{'wallet':69000,'game':200},'flow':{'state':'closed','available_actions':['init','spin']}}
    demo.events.append({'request':{'command':command},'response':response});return response
   demo.call=call
   with gate:result=x.finish(original,gate=gate,fresh_launch=launch,fetch_source=source,private_checkpoint=lambda *args:None)
   self.assertEqual(calls,[('spin',{'bet':10,'purchased_feature':'bonus_buy_1_chance'}),('respin',None)])
   self.assertTrue(result['modes'][-1]['financial_verified']);self.assertEqual(result['modes'][-1]['final_balance'],{'wallet':69000,'game':200})
