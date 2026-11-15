import copy,json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import retry_conditional_modes as x

class ConditionalRetries(unittest.TestCase):
 def fixture(self,statuses=('needs_trigger','closed'),failure=False):
  digest='f'*64;common=dict(protocol='native-rocket-dice',command='roll',cost_native=100,source_sha256=digest,game_id='RocketDice',options={'bet':100,'kind':'over','score':2})
  modes=[dict(common,name='normal',risk_chosen=None),dict(common,name='risk:1,2,3',risk_chosen=[1,2,3])]
  terminal=lambda balance:{'balance':balance,'game':{'state':'closed'},'available_commands':['init','roll']}
  initial=dict(terminal(1000),options={'currency':{'code':'FUN','subunits':100}})
  events=[{'status':200,'request':{'command':'init'},'response':initial},{'status':200,'request':{'command':'roll','options':modes[0]['options']},'response':terminal(900)},{'status':200,'request':{'command':'roll','options':modes[1]['options']},'response':terminal(800)}]
  report={'game':{'game_id':'RocketDice'},'protocol':'native-rocket-dice','protocol_metadata':{'source_sha256':digest,'native_tables_verified':True,'game_id':'RocketDice','protocol':'native-rocket-dice'},'status':'partial','declared_modes':modes,'modes':[{'mode':modes[0],'status':'closed','first_event':1,'last_event':1},{'mode':modes[1],'status':'needs_trigger','first_event':2,'last_event':2}],'events':events,'checks':[{'ok':True},{'ok':True}]}
  calls=[];pending=iter(statuses);d=SimpleNamespace(prev=terminal(800),last_response=terminal(800),events=copy.deepcopy(events),money_checks=copy.deepcopy(report['checks']),protocol_metadata=copy.deepcopy(report['protocol_metadata']))
  def call(command,options=None):
   calls.append((command,copy.deepcopy(options)));response=terminal(d.prev['balance']-100);d.events.append({'status':200,'request':{'command':command,'options':copy.deepcopy(options)},'response':response});d.last_response=response;return response
  d.call=call
  def mode(mode,initial):
   start=len(d.events);response=d.call(mode['command'],mode['options']);d.prev=response
   if failure:raise ValueError('native validation failed')
   d.money_checks.append({'ok':True,'cost_native':100});return dict(mode=copy.deepcopy(mode),status=next(pending),first_event=start,last_event=len(d.events)-1,final_balance=response['balance'],final_state='closed')
  d.run_mode=mode
  gate=SimpleNamespace(check=lambda:None)
  return report,d,calls,gate
 def explore(self,report,d,gate,**options):
  proof={'fresh_source_verified':True,'source_sha256':report['protocol_metadata']['source_sha256']}
  with patch.object(x,'verify_source',return_value=proof):return x.explore(d,report,authorized=True,max_additional_attempts=options.pop('max_additional_attempts',20),max_debit_native=options.pop('max_debit_native',1000),gate=gate,checkpoint=lambda *args:None,fetch_source=lambda url:self.fail('No network'),**options)
 def test_only_needs_trigger_mode_retried_and_all_attempts_retained(self):
  report,d,calls,gate=self.fixture();before=copy.deepcopy(report);result=self.explore(report,d,gate)
  self.assertEqual(report,before);self.assertEqual(result['modes'][0],before['modes'][0]);self.assertEqual(len(calls),2)
  top=result['modes'][1];self.assertEqual(top['status'],'closed');self.assertEqual(len(top['attempts']),3);self.assertEqual(top['attempts'][0]['result'],before['modes'][1]);self.assertEqual(top['attempts'][-1]['cost_native'],100)
  self.assertEqual(result['conditional_exploration']['gross_debit_native'],200);self.assertEqual(result['status'],'complete_declared_modes')
 def test_attempt_and_budget_caps_leave_terminal_unreached_partial(self):
  report,d,calls,gate=self.fixture(('needs_trigger',)*4);result=self.explore(report,d,gate,max_additional_attempts=2)
  self.assertEqual(len(calls),2);self.assertEqual(result['status'],'partial')
  report,d,calls,gate=self.fixture(('needs_trigger',)*4);result=self.explore(report,d,gate,max_debit_native=150)
  self.assertEqual(len(calls),1);self.assertEqual(result['conditional_exploration']['stop_reason'],'native_debit_budget_exhausted');self.assertEqual(result['status'],'partial')
 def test_validation_failure_never_retries_and_restores_call_method(self):
  report,d,calls,gate=self.fixture(failure=True);original=d.call;result=self.explore(report,d,gate)
  self.assertEqual(len(calls),1);self.assertIs(d.call,original);self.assertEqual(result['status'],'needs_review');self.assertEqual(result['modes'][1]['attempts'][-1]['status'],'validation_failed_or_uncertain');self.assertFalse(result['checks'][-1]['ok'])
 def test_optional_native_debit_is_capped_before_transport_without_retry(self):
  report,d,calls,gate=self.fixture();original_mode=d.run_mode
  def mode(mode,initial):
   response=d.call(mode['command'],mode['options']);d.prev=response
   d.call('double');self.fail('Over-budget optional action must not reach transport')
  d.run_mode=mode
  actual=x._request_cost
  def price(protocol,gid,request,initial,current,mode,paid_seen):
   return 100 if request['command']=='double' else actual(protocol,gid,request,initial,current,mode,paid_seen)
  with patch.object(x,'_request_cost',side_effect=price):result=self.explore(report,d,gate,max_debit_native=150)
  self.assertEqual(len(calls),1);self.assertEqual(result['status'],'needs_review');self.assertEqual(result['conditional_exploration']['gross_debit_native'],100)
 def test_snapshots_preserve_native_transport_truth(self):
  saved=[];demo=SimpleNamespace(checkpoint=lambda operation:saved.append(copy.deepcopy(operation)))
  snapshot=x.preserve_native_checkpoint(demo,{'command':'finish','status':'received'})
  snapshot('before_mode');self.assertEqual(saved[-1]['status'],'received')
  demo.checkpoint({'command':'roll','status':'sending'});snapshot('before_request');self.assertEqual(saved[-1]['status'],'sending')
  demo.checkpoint({'command':'roll','status':'uncertain'});snapshot('attempt_failed_no_retry');self.assertEqual(saved[-1]['status'],'uncertain')
  demo.checkpoint({'command':'roll','status':'http_rejection','http_status':422});snapshot('exploration_finished');self.assertEqual(saved[-1]['http_status'],422);self.assertEqual(saved[-1]['status'],'http_rejection')
 def test_failed_native_check_forbids_even_next_continuation(self):
  report,d,calls,gate=self.fixture()
  def mode(mode,initial):
   d.prev=d.call(mode['command'],mode['options']);d.money_checks.append({'ok':False});d.call('finish')
  d.run_mode=mode;result=self.explore(report,d,gate)
  self.assertEqual(len(calls),1);self.assertEqual(result['status'],'needs_review')
 def test_explicit_authorization_limit_and_scope_required(self):
  report,d,calls,gate=self.fixture()
  with self.assertRaises(ValueError):x.explore(d,report,authorized=False,max_additional_attempts=20,max_debit_native=1000,gate=gate,checkpoint=lambda *a:None,fetch_source=lambda *a:None)
  with self.assertRaises(ValueError):self.explore(report,d,gate,max_additional_attempts=101)
  report['checks'][0]['ok']=False
  with self.assertRaises(ValueError):self.explore(report,d,gate)
  self.assertFalse(calls)
 def test_fresh_cached_rocket_source_proof_matches_old_metadata_and_catalog(self):
  root=Path(__file__).resolve().parent;report=json.loads((root/'live/RocketDice.json').read_text(encoding='utf8'));directory=root.parents[1]/'bgaming-private-chat4/research/legacy/RocketDice'
  def fetch(url):return (directory/('loader.js' if url.endswith('loader.js') else report['protocol_metadata']['client_version']+'/bundle.js')).read_bytes()
  proof=x.verify_source(report,fetch)
  self.assertTrue(proof['fresh_source_verified']);self.assertEqual(proof['source_sha256'],report['protocol_metadata']['source_sha256'])
 def test_fresh_cached_blackjack_source_proof_matches_old_metadata_and_catalog(self):
  root=Path(__file__).resolve().parent;report=json.loads((root/'live/ClassicMultihandBlackjack.json').read_text(encoding='utf8'));directory=root.parents[1]/'bgaming-private-chat4/research/legacy/ClassicMultihandBlackjack'
  def fetch(url):return (directory/('loader.js' if url.endswith('loader.js') else report['protocol_metadata']['client_version']+'/bundle.js')).read_bytes()
  proof=x.verify_source(report,fetch)
  self.assertTrue(proof['fresh_source_verified']);self.assertEqual(len(proof['checks']),2)
 def test_classic_casino_family_selects_shared_casino_source_only(self):
  import hashlib
  report,d,calls,gate=self.fixture();report['protocol']='blackjack-extra';source=b'unit-test literal pinned source';old=report['protocol_metadata'];old.update(protocol='blackjack-extra',client_family='classic-casino',source_url='https://cdn.bgaming-network.com/html/casino.min.js',source_sha256=hashlib.sha256(source).hexdigest());urls=[]
  def fetch(url):urls.append(url);return source
  with patch('blackjack_extra.metadata',return_value={'protocol':'blackjack-extra'}),patch('blackjack_extra.plan',return_value=report['declared_modes']):proof=x.verify_source(report,fetch)
  self.assertEqual(urls,[old['source_url']]);self.assertTrue(proof['fresh_source_verified'])
