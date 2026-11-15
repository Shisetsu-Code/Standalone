import copy,json,tempfile,unittest,urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import continue_all_lucky_received as x
from run_demo_qa import Demo
from test_all_lucky_variants import config,CACHE

def initial(lines=5):
 return dict(api_version='2',options={'available_bets':[10,20],'currency':{'code':'FUN','subunits':100},'lines':[[0]*5 for _ in range(lines)]},balance={'wallet':100000,'game':0},flow={'round_id':None,'last_action_id':None,'state':'ready','command':'init','available_actions':['init','spin']})

def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf8')

class Gate:
 def __init__(self,root,last_launch_epoch,**kwargs):self.last_launch_epoch=last_launch_epoch
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def check(self):pass
 def reserve(self):self.last_launch_epoch+=60;return self.last_launch_epoch

class Continuation(unittest.TestCase):
 def inputs(self,root,private):
  v=private/'all-lucky-variants-v3';selector=config();cfg=config('AllLuckyClover5');base=cfg['resources_path'];cfg.update(resources_root_path=base,resources_path=base+'/'+x.VERSION,game_bundle_source=base+'/'+x.VERSION+'/bundle.js');r=initial();sel={'wallet':100000,'game':0}
  req=dict(method='POST',url=cfg['api'],body='{"command":"init"}',status='received',http_status=200,final_url=cfg['api'],response_headers=[['Set-Cookie','native=latest; Path=/; Secure']],response=r)
  get=dict(method='GET',url=selector['lobby_launch_url']+'&game=AllLuckyClover5&from=AllLuckyClover',body=None,status='received',http_status=200,final_url=cfg['api'],response_headers=[['Set-Cookie','native=earlier; Path=/; Secure']],response=config('AllLuckyClover5'))
  session=dict(fresh_demo=True,game_id='AllLuckyClover',last_request={'command':'init'},last_response=sel,public_events=[{'request':{'command':'init'},'response':sel,'status':200}],operation={'command':'init','status':'received'},cookies=[],api=selector['api'],csrf_name=selector['csrfTokenHeaderName'],csrf_value=selector['csrfTokenHeaderValue'],page='https://demo.bgaming-network.com/games/AllLuckyClover')
  for name,value in [('checkpoint.json',dict(stage='variant_init_received',payload=dict(variant='AllLuckyClover5',response=r,bootstrap=cfg,last_launch_epoch=1000))),('request-checkpoint.json',req),('selector-init.json',sel),('selector-bootstrap.json',selector),('requests.json',[get,req])]:write(v/name,value)
  write(private/'AllLuckyClover.session.json',session);write(root/'run-state.json',dict(active_game=None,last_launch_epoch=1000,results={}));(root/'STOP').write_text('CHECKPOINT_MAINTENANCE');write(root/'all-lucky-variants-live.json',{'status':'needs_review','reason':'old init-only attempt'});write(root/'live/AllLuckyClover.json',{'selector':'must remain unchanged'})
  return session,[get,req]
 def test_captured_native_set_cookie_is_applied_in_receipt_order(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);session,records=self.inputs(root/'root',root/'private');opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor());jar=x.restore_own_cookies(opener,session,records)
   request=urllib.request.Request(records[-1]['final_url']);jar.add_cookie_header(request);self.assertEqual(request.get_header('Cookie'),'native=latest')
   records[-1]['final_url']='https://outside.example/';
   with self.assertRaises(ValueError):x.restore_own_cookies(opener,session,records)
 def test_pinned_collect_preserves_round_and_native_effective_balance(self):
  before=dict(balance={'wallet':900,'game':40},flow={'state':'gamble','round_id':'own-round','available_actions':['init','gamble','close']});response=dict(balance={'wallet':940,'game':0},flow={'state':'closed','command':'close','round_id':'own-round'});calls=[]
  d=SimpleNamespace(protocol_metadata={'api2_collect_close_verified':True},money_checks=[],call=lambda command:(calls.append(command) or response));self.assertEqual(x.collect_slots(d,before),response);self.assertEqual(calls,['close']);self.assertTrue(d.money_checks[-1]['ok'])
  response['balance']['wallet']=941
  with self.assertRaises(ValueError):x.collect_slots(d,before)
  self.assertFalse(d.money_checks[-1]['ok'])
 def test_unknown_slot_state_sends_nothing(self):
  calls=[];d=SimpleNamespace(protocol_metadata={'protocol':'legacy-api2-slots'},settle=lambda response:calls.append(response));x.install_settlement(d)
  with self.assertRaises(ValueError):d.settle({'flow':{'state':'unknown','available_actions':['play_bonus']}})
  self.assertEqual(calls,[])
 def test_full_offline_four_slots_never_replays_variant5_get_or_init(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/'root';private=Path(directory)/'private';self.inputs(root,private);wire=[];gameplay=[];original=(root/'live/AllLuckyClover.json').read_bytes();v3=(private/'all-lucky-variants-v3/checkpoint.json').read_bytes()
   class FakeDemo(Demo):
    def checkpoint(self,operation):self.operation=copy.deepcopy(operation)
    def call(self,command,options=None):
     gameplay.append((self.game['game_id'],command,copy.deepcopy(options)))
     response=dict(balance={'wallet':99990,'game':0},flow={'state':'closed','command':command,'round_id':'round-'+self.game['game_id'],'available_actions':['init','spin']})
     self.events.append({'request':{'command':command,'options':options},'response':response,'status':200});self.last_response=response;return response
   def transport(method,url,headers,body):
    self.assertTrue((private/'all-lucky-received-continuation/original/checkpoint.json').exists());wire.append((method,url,body))
    if method=='STATIC':return (CACHE/('loader.js' if url.endswith('loader.js') else 'v2.0.90_v14.19.2/bundle.js')).read_bytes()
    if method=='GET':return config(url.split('game=')[1].split('&')[0])
    gid=url.split('/api/')[1].split('/')[0];self.assertEqual(json.loads(body),{'command':'init'});return initial(int(gid.removeprefix('AllLuckyClover')))
   with patch.object(x,'save',side_effect=write):result=x.run(root=root,private=private,demo_factory=FakeDemo,transport=transport,gate_factory=Gate,output=lambda value:None)
   self.assertEqual(result['status'],'complete_declared_modes');self.assertEqual(len(result['variant_reports']),4);self.assertEqual([v[0] for v in wire if v[0]!='STATIC'],['GET','POST']*3);self.assertEqual([v[0] for v in gameplay],list(x.VARIANTS));self.assertTrue(all(command=='spin' and args=={'bet':10} for _,command,args in gameplay));self.assertEqual(original,(root/'live/AllLuckyClover.json').read_bytes());self.assertEqual(v3,(private/'all-lucky-variants-v3/checkpoint.json').read_bytes());self.assertEqual(json.loads((root/'run-state.json').read_text())['active_game'],None)
   with patch.object(x,'save',side_effect=write):
    with self.assertRaises(ValueError):x.run(root=root,private=private,demo_factory=FakeDemo,transport=lambda *args:self.fail('No replay'),gate_factory=Gate,output=lambda value:None)
 def test_stop_blocks_before_archive_or_requests(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/'root';private=Path(directory)/'private';self.inputs(root,private);(root/'STOP').write_text('STOP')
   with self.assertRaises(ValueError):x.run(root=root,private=private,transport=lambda *args:self.fail('No network'),gate_factory=Gate)
   self.assertFalse((private/'all-lucky-received-continuation/attempt.json').exists())
 def test_first_native_validation_failure_preserves_receipt_and_stops_later_variants(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/'root';private=Path(directory)/'private';self.inputs(root,private);calls=[]
   class BadDemo(Demo):
    def checkpoint(self,operation):pass
    def call(self,command,options=None):
     calls.append(command);response=dict(balance={'wallet':99989,'game':0},flow={'state':'closed','command':command,'round_id':'own','available_actions':['init','spin']});self.events.append(dict(request={'command':command,'options':options},response=response,status=200));self.last_response=response;return response
   def transport(method,url,headers,body):
    self.assertEqual(method,'STATIC');return (CACHE/('loader.js' if url.endswith('loader.js') else 'v2.0.90_v14.19.2/bundle.js')).read_bytes()
   with patch.object(x,'save',side_effect=write):result=x.run(root=root,private=private,demo_factory=BadDemo,transport=transport,gate_factory=Gate,output=lambda value:None)
   self.assertEqual(result['status'],'needs_review');self.assertEqual(calls,['spin']);report=json.loads((root/'live/selector-variants/AllLuckyClover5.json').read_text());self.assertEqual(len(report['events']),2);self.assertFalse(report['checks'][-1]['ok']);self.assertEqual(json.loads((root/'run-state.json').read_text())['active_game'],None)
