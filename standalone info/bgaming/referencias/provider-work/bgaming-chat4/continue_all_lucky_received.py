"""Parent-only AllLucky continuation. Import is inert; never replay received init."""
import base64,copy,hashlib,http.cookiejar,json,urllib.error,urllib.request
from email.message import Message
from pathlib import Path
from all_lucky_variants import (VARIANTS,VERSION,BUNDLE_SHA256,VariantGate,SelectorPreparer,
 prepare_received,official_url,validate_config)
from diagnose_all_lucky_redirect import OfficialRedirectHandler,_opener,parse_body
from checkpoint_guard import acquire,require_inactive
from run_demo_qa import ROOT,PRIVATE,Demo,save,now

GID='AllLuckyClover'

def write_once(path,raw):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as stream:stream.write(raw)

def jar_of(opener):
 jar=next((h.cookiejar for h in opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor)),None)
 if jar is None:raise ValueError('Own cookie jar required')
 return jar

def cookies_of(opener):
 return [dict(name=c.name,value=c.value,domain=c.domain,path=c.path,secure=c.secure,expires=c.expires) for c in jar_of(opener)]

def restore_own_cookies(opener,session,records):
 """Only this suite's fresh init session plus its captured native HTTP receipts."""
 if session.get('fresh_demo') is not True or session.get('game_id')!=GID or session.get('operation',{}).get('status')!='received' or session.get('last_request',{}).get('command')!='init' or len(session.get('public_events',[]))!=1:raise ValueError('Own init-only selector context required')
 jar=jar_of(opener)
 for c in session['cookies']:
  jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 for record in records:
  if record.get('status')!='received' or record.get('http_status')!=200:raise ValueError('Captured own HTTP receipt is not accepted')
  url=official_url(record['final_url']);headers=Message()
  for name,value in record['response_headers']:headers.add_header(name,value)
  class Received:
   def info(self):return headers
  jar.extract_cookies(Received(),urllib.request.Request(url))
 return jar

def collect_proof(raw):
 if hashlib.sha256(raw).hexdigest()!=BUNDLE_SHA256 or b'command:Ye.isApi2?"close":"finish"' not in raw:raise ValueError('Pinned API2 collect source differs')
 return dict(api2_collect_close_verified=True,api2_collect_source_sha256=BUNDLE_SHA256)

def collect_slots(demo,before):
 f=before.get('flow',{});actions=set(f.get('available_actions',[]))-{'init'}
 if not demo.protocol_metadata.get('api2_collect_close_verified') or f.get('state') not in ('gamble','check_card') or actions!={'gamble','close'} or not f.get('round_id'):raise ValueError('Source/native optional collect is not proved')
 old=before.get('balance',{})
 if set(old)!={'wallet','game'} or any(type(v) is not int or v<0 for v in old.values()):raise ValueError('Native collect amounts unproved')
 response=demo.call('close');a=response.get('flow',{});new=response.get('balance',{})
 expected=sum(old.values());actual=sum(new.values()) if set(new)=={'wallet','game'} and all(type(v) is int and v>=0 for v in new.values()) else None
 check=dict(kind='all_lucky_api2_collect_native',round_preserved=a.get('round_id')==f['round_id'],expected_effective_native=expected,actual_effective_native=actual,ok=a.get('round_id')==f['round_id'] and a.get('state')=='closed' and a.get('command')=='close' and actual==expected)
 demo.money_checks.append(check)
 if not check['ok']:raise ValueError('Native collect round/balance failed; no retry')
 return response

def install_settlement(demo):
 original=demo.settle
 def settle(response):
  if demo.protocol_metadata.get('protocol')!='legacy-api2-slots':return original(response)
  def offered(value):return value.get('flow',{}).get('state') in ('gamble','check_card') and set(value.get('flow',{}).get('available_actions',[]))-{'init'}=={'gamble','close'}
  if offered(response):return collect_slots(demo,response)
  if response.get('flow',{}).get('state')=='closed':return original(response)
  actions=set(response.get('flow',{}).get('available_actions',[]))-{'init'}
  if response.get('flow',{}).get('state') not in ('freespin','respin') or actions not in ({'freespin'},{'respin'}):raise ValueError('Unknown AllLucky slot state preserved without input')
  try:return original(response)
  except RuntimeError as error:
   latest=getattr(demo,'last_response',None)
   if str(error)!='Unrecognized continuation or choice; manual review required' or not isinstance(latest,dict) or not offered(latest) or any(c.get('ok') is False for c in demo.money_checks):raise
   return collect_slots(demo,latest)
 demo.settle=settle

class PrivateTransport:
 def __init__(self,demo,gate,checkpoint,work,transport=None):self.demo=demo;self.gate=gate;self.checkpoint=checkpoint;self.work=work;self.records=[];self.transport=transport
 def fetch(self,url):
  self.gate.check();official_url(url)
  if self.transport is not None:return self.transport('STATIC',url,{},None)
  with _opener(OfficialRedirectHandler(self.checkpoint,self.gate.check),self.demo.opener).open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
   official_url(response.url);raw=response.read()
   self.checkpoint('static_source_received',dict(url=response.url,http_status=response.status,response_headers=list(response.headers.items()),response_body_base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest()))
   if response.status!=200:raise ValueError('Static source not accepted')
   return raw
 def request(self,method,url,headers,body):
  self.gate.check();official_url(url);marker=dict(method=method,url=url,headers=headers,body=body.decode('utf8') if body else None,status='sending')
  self.checkpoint('before_native_selector_or_init',marker)
  if self.transport is not None:return self.transport(method,url,headers,body)
  try:
   with _opener(OfficialRedirectHandler(self.checkpoint,self.gate.check),self.demo.opener).open(urllib.request.Request(url,data=body,headers=dict(headers,**{'User-Agent':'Mozilla/5.0'}),method=method),timeout=45) as response:
    official_url(response.url);raw=response.read();marker.update(final_url=response.url,http_status=response.status,response_headers=list(response.headers.items()),response_body_base64=base64.b64encode(raw).decode(),response_sha256=hashlib.sha256(raw).hexdigest())
    self.checkpoint('native_http_body_received',marker);kind,value=parse_body(raw)
    if response.status!=200 or not isinstance(value,dict) or kind not in ('bootstrap_options_json','bootstrap_options_html','json_other') or value.get('errors'):raise ValueError('Native selector/init response requires review')
    marker.update(status='received',response=value);self.records.append(copy.deepcopy(marker));save(self.work/'requests.json',self.records);self.checkpoint('native_selector_or_init_received',marker);return value
  except Exception as error:
   if isinstance(error,urllib.error.HTTPError):
    raw=error.read();marker.update(status='http_rejection',http_status=error.code,response_headers=list(error.headers.items()),response_body_base64=base64.b64encode(raw).decode())
   else:marker.update(status='uncertain_or_validation_failed',error_type=type(error).__name__)
   self.checkpoint('native_request_failed_no_retry',marker);raise

def run(*,root=ROOT,private=PRIVATE,demo_factory=Demo,transport=None,gate_factory=VariantGate,output=print):
 root=Path(root).resolve();private=Path(private).resolve();lock=acquire(root/'runner.lock');started=False;state=None;aggregate=None;current=None
 work=private/'all-lucky-received-continuation';dest=root/'live/selector-variants';prior=root/'all-lucky-variants-live.json';source_dir=private/'all-lucky-variants-v3'
 try:
  state=json.loads((root/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
  if (root/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Exact maintenance marker required')
  if (work/'attempt.json').exists() or any((dest/(gid+'.json')).exists() for gid in VARIANTS):raise ValueError('Existing continuation/variant evidence forbids replay')
  paths=[source_dir/name for name in ('checkpoint.json','request-checkpoint.json','selector-init.json','selector-bootstrap.json','requests.json')]+[private/(GID+'.session.json')]
  raw={p.name:p.read_bytes() for p in paths};checkpoint=json.loads(raw['checkpoint.json']);record=json.loads(raw['request-checkpoint.json']);selector_initial=json.loads(raw['selector-init.json']);selector_cfg=json.loads(raw['selector-bootstrap.json']);session=json.loads(raw[GID+'.session.json']);records=json.loads(raw['requests.json'])
  if checkpoint.get('stage')!='variant_init_received' or checkpoint.get('payload',{}).get('variant')!=VARIANTS[0] or len(records)!=2 or records[-1]!=record:raise ValueError('Expected one accepted variant GET/init pair required')
  validate_config(selector_cfg,GID)
  expected_get=selector_cfg['lobby_launch_url']+('&' if '?' in selector_cfg['lobby_launch_url'] else '?')+'game='+VARIANTS[0]+'&from='+GID
  if records[0].get('method')!='GET' or records[0].get('url')!=expected_get or records[0].get('body') is not None or records[0].get('response',{}).get('identifier')!=VARIANTS[0] or records[0].get('response',{}).get('api')!=checkpoint['payload']['bootstrap'].get('api'):raise ValueError('Original captured selector transition differs')
  if session.get('last_response')!=selector_initial or session.get('api')!=selector_cfg['api'] or session.get('csrf_name')!=selector_cfg['csrfTokenHeaderName'] or session.get('csrf_value')!=selector_cfg['csrfTokenHeaderValue']:raise ValueError('Original selector init/context differs')
  selector=demo_factory(dict(game_id=GID,title=GID));restore_own_cookies(selector.opener,session,records);selector.page=official_url(session['page'])
  for name,content in raw.items():write_once(work/'original'/name,content)
  if prior.exists():write_once(work/'original/aggregate-before.json',prior.read_bytes())
  write_once(work/'attempt.json',json.dumps(dict(started_at=now(),operation='received_variant5_then_remaining_three_slots_only',input_sha256={name:hashlib.sha256(content).hexdigest() for name,content in raw.items()}),indent=2).encode());started=True
  aggregate=dict(game=dict(game_id=GID,title=GID),status='running',selector_initial=selector.clean.clean(selector_initial),variant_reports=[],resumed_received_variant=VARIANTS[0],original_context_archive='all-lucky-received-continuation/original')
  state.update(active_game=VARIANTS[0],updated_at=now());save(root/'run-state.json',state);sequence=0
  with gate_factory(root,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
   def persist(stage,payload):
    nonlocal sequence
    sequence+=1;save(work/f'checkpoint-{sequence:05d}.json',dict(stage=stage,payload=copy.deepcopy(payload),cookies=cookies_of(selector.opener),time=now()))
    if payload.get('last_launch_epoch') is not None:state.update(last_launch_epoch=payload['last_launch_epoch'],active_game=payload.get('variant',VARIANTS[0]),updated_at=now());save(root/'run-state.json',state)
    if current is not None:current['report'].update(events=current['demo'].events,checks=current['demo'].money_checks);save(current['path'],current['report'])
   io=PrivateTransport(selector,gate,persist,work,transport)
   try:
    prepared=prepare_received(checkpoint,received_request=record,selector_initial=selector_initial,fresh_suite_owned=True,fetch_source=io.fetch,gate=gate)
    # No fresh launch/init for variant5. Reserve suite pacing before its wager.
    persist('received_variant5_pacing_reserved',dict(variant=VARIANTS[0],last_launch_epoch=gate.reserve()))
    cfg=copy.deepcopy(prepared.bootstrap);cfg['resources_path']=cfg['resources_root_path'];cfg.pop('resources_root_path',None);cfg.pop('game_bundle_source',None)
    preparer=SelectorPreparer(selector_cfg,selector_initial,fresh_suite_owned=True,fetch_source=io.fetch,request_json=io.request,private_checkpoint=persist,gate=gate);preparer.current_config=cfg;preparer.selected.add(VARIANTS[0])
    for gid in VARIANTS:
     if gid!=VARIANTS[0]:current=None;prepared=preparer.prepare(gid)
     d=demo_factory(dict(game_id=gid,title=gid));d.opener=selector.opener;d.page=selector.page;d.api=official_url(prepared.bootstrap['api']);d.csrf_name=prepared.bootstrap['csrfTokenHeaderName'];d.csrf_value=prepared.bootstrap['csrfTokenHeaderValue'];d.protocol=prepared.metadata['protocol'];d.protocol_metadata=copy.deepcopy(prepared.metadata)
     if d.protocol=='legacy-api2-slots':d.protocol_metadata.update(collect_proof(io.fetch(prepared.bootstrap['game_bundle_source'])))
     d.last_response=copy.deepcopy(prepared.initial);d.prev=d.last_response;d.events=[dict(time=now(),request={'command':'init'},response=d.clean.clean(d.last_response),status=200,kind='resumed_received_selector_variant_init' if gid==VARIANTS[0] else 'fresh_selector_variant_init')];d.money_checks=[]
     report=dict(game=d.game,status='running',protocol=d.protocol,protocol_metadata=d.protocol_metadata,events=d.events,checks=d.money_checks,modes=[],declared_modes=prepared.modes,selector_preparation=prepared.public_record())
     path=dest/(gid+'.json');current=dict(demo=d,report=report,path=path);d.checkpoint(dict(status='received',command='init'));save(path,report);install_settlement(d);native_call=d.call
     def guarded_call(command,options=None):
      gate.check()
      if any(c.get('ok') is False for c in d.money_checks):raise ValueError('Failed native check forbids another request')
      persist('before_variant_gameplay',dict(variant=gid,command=command))
      try:response=native_call(command,options) if options is not None else native_call(command)
      except Exception:persist('variant_gameplay_failed_no_retry',dict(variant=gid,command=command));raise
      persist('variant_gameplay_received',dict(variant=gid,command=command))
      if response.get('errors') or d.events[-1].get('status')!=200:raise ValueError('Native response rejected; no retry')
      return response
     d.call=guarded_call
     for mode in prepared.modes:
      persist('before_variant_mode',dict(variant=gid,mode=mode));report['modes'].append(d.run_mode(copy.deepcopy(mode),prepared.initial));persist('after_variant_mode',dict(variant=gid,mode=mode))
     if any(c.get('ok') is False for c in d.money_checks) or any(m.get('status')!='closed' for m in report['modes']):raise ValueError('Variant native mode did not close with passing checks')
     report.update(status='complete_declared_modes',finished_at=now());save(path,report);aggregate['variant_reports'].append(dict(game_id=gid,status=report['status'],report=str(path.relative_to(root))));save(prior,aggregate);state.setdefault('results',{})[gid]=dict(status=report['status'],modes_closed=len(report['modes']),report=str(path.relative_to(root)));output(gid+' '+report['status'])
    aggregate['status']='complete_declared_modes'
   except Exception as error:
    aggregate.update(status='needs_review',error_type=type(error).__name__)
    if current is not None:
     current['report'].update(status='needs_review',error_type=type(error).__name__,events=current['demo'].events,checks=current['demo'].money_checks,finished_at=now());save(current['path'],current['report']);gid=current['demo'].game['game_id']
     aggregate['variant_reports']=[v for v in aggregate['variant_reports'] if v['game_id']!=gid]+[dict(game_id=gid,status='needs_review',report=str(current['path'].relative_to(root)))];state.setdefault('results',{})[gid]=dict(status='needs_review',report=str(current['path'].relative_to(root)))
    persist('continuation_failed_no_replay',dict(error_type=type(error).__name__))
  aggregate['finished_at']=now();save(prior,aggregate);return aggregate
 finally:
  try:
   if started:
    if aggregate is None:aggregate=dict(status='needs_review',variant_reports=[])
    save(prior,aggregate);save(work/'final-cookies.json',cookies_of(selector.opener));state.update(active_game=None,updated_at=now());save(root/'run-state.json',state)
  finally:lock.close()

if __name__=='__main__':
 result=run();print('AllLucky slots '+result['status'],flush=True)
