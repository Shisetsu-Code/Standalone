import copy
import json
from pathlib import Path
import tempfile
import unittest

from all_lucky_variants import SelectorPreparer, VariantGate, VARIANTS, source_contract, variant_plan, prepare_received

ROOT=Path(__file__).resolve().parents[2]
CACHE=ROOT/'bgaming-private-chat4/research/legacy/AllLuckyClover'

def config(identifier='AllLuckyClover'):
 return dict(identifier=identifier,currency='FUN',server_id='demo',api='https://demo.bgaming-network.com/api/'+identifier+'/suite-private',rules_url='https://demo.bgaming-network.com/rules/'+identifier,lobby_launch_url='https://demo.bgaming-network.com/lobby/suite-private?server=demo',csrfTokenHeaderName='X-Suite-CSRF',csrfTokenHeaderValue='private-'+identifier,resources_path='https://cdn.bgaming-network.com/html/AllLuckyClover',game_bundle_source='https://cdn.bgaming-network.com/html/AllLuckyClover/bundle.js',ui={})

class LuckyVariants(unittest.TestCase):
 def actual_api2(self):
  # Native subset copied from v3 variant_init_received, before any wager.
  # Keep this fixture independent of the parent's moving private checkpoint.
  return dict(api_version='2',options={'available_bets':[10,20,30,40,50,100,150,200,300,500,1000],'default_bet':10,'currency':{'code':'FUN','symbol':'FUN','subunits':100,'exponent':2},'lines':[[1,1,1,1,1],[0,0,0,0,0],[2,2,2,2,2],[0,1,2,1,0],[2,1,0,1,2]]},balance={'wallet':100000,'game':0},flow={'round_id':None,'last_action_id':None,'state':'ready','command':'init','available_actions':['init','spin']})
 def test_actual_received_api2_total_bet_is_10_not_50_for_five_lines(self):
  initial=self.actual_api2();before=copy.deepcopy(initial);source=(CACHE/'v2.0.90_v14.19.2/bundle.js').read_bytes()
  meta,modes=variant_plan(initial,'AllLuckyClover5',source)
  self.assertEqual(initial,before);self.assertTrue(meta['api2_native_bet_verified']);self.assertEqual(meta['protocol'],'legacy-api2-slots');self.assertEqual(modes,[dict(name='normal',command='spin',options={'bet':10},cost_native=10)])
  wrong=copy.deepcopy(initial);wrong['options']['line_bets']=[10]
  with self.assertRaises(ValueError):variant_plan(wrong,'AllLuckyClover5',source)
  with self.assertRaises(ValueError):variant_plan(initial,'AllLuckyClover20',source)
  wrong=copy.deepcopy(initial);wrong['flow']['state']='freespin'
  with self.assertRaises(ValueError):variant_plan(wrong,'AllLuckyClover5',source)
 def test_api2_selector_prepare_uses_native_plan_and_public_protocol(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root,initial=self.actual_api2())
   with gate:prepared=prep.prepare('AllLuckyClover5')
   self.assertEqual(len(calls),2);self.assertEqual(prepared.modes[0]['options'],{'bet':10});self.assertEqual(prepared.public_record()['protocol'],'legacy-api2-slots')
 def test_received_api2_resume_fetches_only_pinned_static_source_no_api_or_selector(self):
  initial=self.actual_api2();cfg=config('AllLuckyClover5');base=cfg['resources_path'];cfg.update(resources_root_path=base,resources_path=base+'/v2.0.90_v14.19.2',game_bundle_source=base+'/v2.0.90_v14.19.2/bundle.js')
  received=dict(stage='variant_init_received',payload=dict(variant='AllLuckyClover5',bootstrap=cfg,response=initial,last_launch_epoch=1000))
  record=dict(status='received',method='POST',http_status=200,response=initial,url=cfg['api'],body='{"command":"init"}')
  before=copy.deepcopy((received,record));calls=[]
  def fetch(url):
   calls.append(url);return (CACHE/('loader.js' if url.endswith('loader.js') else 'v2.0.90_v14.19.2/bundle.js')).read_bytes()
  with tempfile.TemporaryDirectory() as root:
   with VariantGate(root,last_launch_epoch=1000) as gate:prepared=prepare_received(received,received_request=record,selector_initial={'wallet':100000},fresh_suite_owned=True,fetch_source=fetch,gate=gate)
  self.assertEqual((received,record),before);self.assertEqual(len(calls),2);self.assertTrue(all(url.startswith('https://cdn.bgaming-network.com/') for url in calls));self.assertEqual(prepared.modes[0]['cost_native'],10)
  record['body']='{"command":"spin"}'
  with self.assertRaises(ValueError):prepare_received(received,received_request=record,selector_initial={},fresh_suite_owned=True,fetch_source=lambda url:self.fail('No fetch for mismatched receipt'),gate=None)
 def test_real_cached_selector_and_old_slot_source_proofs(self):
  meta=source_contract((CACHE/'loader.js').read_bytes(),(CACHE/'v2.0.90_v14.19.2/bundle.js').read_bytes())
  self.assertEqual(meta['variants'],list(VARIANTS));self.assertTrue(meta['old_slots']['source_verified'])
 def harness(self,root,returned=None,initial=None):
  state={'time':1000.0};calls=[];private=[]
  def sleep(seconds):state['time']+=seconds
  gate=VariantGate(root,last_launch_epoch=1000,clock=lambda:state['time'],sleeper=sleep)
  def fetch(url):
   return (CACHE/('loader.js' if url.endswith('/loader.js') else 'v2.0.90_v14.19.2/bundle.js')).read_bytes()
  def request(method,url,headers,body):
   calls.append((method,url,copy.deepcopy(headers),body,state['time']))
   if method=='GET':return copy.deepcopy(returned or config(url.split('game=')[1].split('&')[0]))
   return copy.deepcopy(initial or dict(api_version='1',balance=100000,options={'currency':{'code':'FUN','subunits':100},'lines':[[0]]*5,'line_bets':[20,40]},game={'state':'idle'},available_commands=['spin']))
  prep=SelectorPreparer(config(),{'wallet':100000,'game':0},fresh_suite_owned=True,fetch_source=fetch,request_json=request,private_checkpoint=lambda stage,data:private.append((stage,copy.deepcopy(data))),gate=gate)
  return prep,gate,calls,private,state
 def test_get_switch_replaces_bootstrap_before_native_variant_init(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root)
   original=copy.deepcopy(prep.selector_initial)
   with gate:
    first=prep.prepare(VARIANTS[0]);second=prep.prepare(VARIANTS[1])
   self.assertEqual([c[0] for c in calls],['GET','POST','GET','POST'])
   self.assertIn('game=AllLuckyClover5&from=AllLuckyClover',calls[0][1])
   self.assertIn('game=AllLuckyClover20&from=AllLuckyClover5',calls[2][1])
   self.assertIsNone(calls[0][3]);self.assertEqual(json.loads(calls[1][3]),{'command':'init'})
   self.assertEqual(calls[1][2]['X-Suite-CSRF'],'private-AllLuckyClover5')
   self.assertIn('/api/AllLuckyClover5/',calls[1][1])
   self.assertGreaterEqual(calls[2][4]-calls[0][4],60)
   self.assertEqual(first.modes[0]['cost_native'],100)
   self.assertEqual(first.public_record()['game_id'],'AllLuckyClover5')
   self.assertNotIn('suite-private',json.dumps(first.public_record()))
   self.assertEqual(prep.selector_initial,original)
   self.assertIn('before_variant_get',[stage for stage,_ in private])
 def test_stop_blocks_get_and_source_init(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root);Path(root,'STOP').write_text('maintenance')
   with gate:
    with self.assertRaises(RuntimeError):prep.prepare(VARIANTS[0])
   self.assertFalse(calls)
 def test_unknown_variant_or_returned_identity_never_initializes(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root,returned=config('OtherGame'))
   with gate:
    with self.assertRaises(ValueError):prep.prepare('AllLuckyClover999')
    with self.assertRaises(ValueError):prep.prepare(VARIANTS[0])
   self.assertEqual([c[0] for c in calls],['GET'])
 def test_selector_only_init_cannot_be_normalized_as_variant(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root,initial={'wallet':100000,'game':0})
   with gate:
    with self.assertRaises(ValueError):prep.prepare(VARIANTS[0])
   self.assertEqual(len(calls),2)
   self.assertEqual(private[-1][0],'variant_init_received')
 def test_requires_fresh_suite_ownership_and_active_lock(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root)
   with self.assertRaises(RuntimeError):prep.prepare(VARIANTS[0])
   self.assertFalse(calls)
 def test_corrupt_source_rejected_before_switch(self):
  with self.assertRaises(ValueError):source_contract((CACHE/'loader.js').read_bytes(),b'changed')
 def test_existing_runner_lock_can_be_borrowed_without_releasing_it(self):
  from checkpoint_guard import acquire
  with tempfile.TemporaryDirectory() as root:
   handle=acquire(Path(root)/'runner.lock')
   try:
    gate=VariantGate(root,last_launch_epoch=0,lock_handle=handle,clock=lambda:1000)
    with gate:self.assertEqual(gate.reserve(),1000)
    self.assertFalse(handle.closed)
   finally:handle.close()
 def test_stop_interrupts_rate_wait_without_network(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root)
   def sleep(seconds):state['time']+=seconds;Path(root,'STOP').write_text('maintenance')
   gate.sleeper=sleep
   with gate:
    with self.assertRaises(RuntimeError):prep.prepare(VARIANTS[0])
   self.assertFalse(calls)
 def test_transport_failure_is_never_retried_or_reused(self):
  with tempfile.TemporaryDirectory() as root:
   prep,gate,calls,private,state=self.harness(root)
   def request(*args):calls.append(args);raise TimeoutError('private-url-not-for-report')
   prep.request_json=request
   with gate:
    with self.assertRaisesRegex(RuntimeError,'no retry'):prep.prepare(VARIANTS[0])
    with self.assertRaises(RuntimeError):prep.prepare(VARIANTS[1])
   self.assertEqual(len(calls),1)
 def test_continue_marker_and_explicit_maintenance_authorization(self):
  with tempfile.TemporaryDirectory() as root:
   stop=Path(root,'STOP');stop.write_text('CONTINUE')
   gate=VariantGate(root,last_launch_epoch=0,clock=lambda:1000)
   with gate:gate.check()
   stop.write_text('CHECKPOINT_MAINTENANCE')
   with gate:
    with self.assertRaises(RuntimeError):gate.check()
   authorized=VariantGate(root,last_launch_epoch=0,clock=lambda:1000,maintenance_authorized=True)
   with authorized:authorized.check()
   self.assertEqual(stop.read_text(),'CHECKPOINT_MAINTENANCE')
   stop.write_text('STOP')
   with authorized:
    with self.assertRaises(RuntimeError):authorized.check()
