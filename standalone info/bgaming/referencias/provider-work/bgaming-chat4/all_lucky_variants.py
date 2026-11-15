"""Parent-executed All Lucky Clover selection and init preparation; no wagers.

request_json(method, url, headers, body_bytes_or_None) must use the ONE fresh
suite-owned cookie jar, validate redirects/status, and never retry requests.
fetch_source(url) returns freshly fetched static bytes, never cached evidence.
private_checkpoint(stage, payload) must preserve payload plus the current cookie
jar privately. Public reports use PreparedVariant.public_record() only.
"""
import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
import re
import time
from urllib.parse import quote, urlsplit

VARIANTS=('AllLuckyClover5','AllLuckyClover20','AllLuckyClover40','AllLuckyClover100')
VERSION='v2.0.90_v14.19.2'
LOADER_SHA256='6ec343315bcd2c933308186b7226e55fa29cd837a94b8c89cf11f5daf696150c'
BUNDLE_SHA256='89ac2e84198bf28ba933dd304089fe9dbd0f725be7e2c4f623940fac998f7c55'

def digest_json(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def official_url(value):
 if not isinstance(value,str):raise ValueError('Official bootstrap URL missing')
 u=urlsplit(value)
 if u.scheme!='https' or not u.hostname or not (u.hostname.endswith('.bgaming-network.com') or u.hostname=='bgaming.com') or u.username or u.password or u.fragment or u.port not in (None,443):raise ValueError('Untrusted bootstrap URL')
 return value

def validate_config(cfg,identifier):
 if not isinstance(cfg,dict) or cfg.get('identifier')!=identifier or cfg.get('currency')!='FUN' or cfg.get('server_id')!='demo':raise ValueError('Selected bootstrap identity/currency/server mismatch')
 for key in ('api','rules_url','lobby_launch_url','resources_path'):official_url(cfg.get(key))
 resource=urlsplit(cfg['resources_path'])
 if resource.hostname!='cdn.bgaming-network.com' or resource.query or resource.path.rstrip('/').endswith('/'+VERSION):raise ValueError('Bootstrap resources do not expose an uninitialized official CDN base')
 name=cfg.get('csrfTokenHeaderName');value=cfg.get('csrfTokenHeaderValue')
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',name) or not isinstance(value,str) or not value or '\r' in value or '\n' in value:raise ValueError('Unverified bootstrap CSRF header')
 return copy.deepcopy(cfg)

def source_contract(loader_raw,bundle_raw):
 if hashlib.sha256(loader_raw).hexdigest()!=LOADER_SHA256 or hashlib.sha256(bundle_raw).hexdigest()!=BUNDLE_SHA256:raise ValueError('Fresh selector source changed; review before selecting a variant')
 loader=loader_raw.decode('utf8');source=bundle_raw.decode('utf8')
 tokens=['ks=["AllLuckyClover5","AllLuckyClover20","AllLuckyClover40","AllLuckyClover100"]','init(){qe.setGameId(ks[Ns])','setGameId(e){_e.currentGameId!==e','_e.lobbyUrl.indexOf("?")>0?"&":"?"','"game="+e+"&from="+_e.currentGameId','_e.setCasinoOptions(t),ve=null,window.initializeCasinoOptions(t),ye()','requestURL(e,t,i){var n,r={method:t?"POST":"GET",headers:this.headers}','this.currentGameId=e.identifier,this.apiUrl=e.api,this.rulesUrl=e.rules_url,this.lobbyUrl=e.lobby_launch_url','this.headers[e.csrfTokenHeaderName]=e.csrfTokenHeaderValue']
 if not all(t in source for t in tokens) or 'res:t="'+VERSION+'"' not in loader or 'e.resources_path+=`/${t}`,e.game_bundle_source=e.resources_path+"/bundle.js"' not in loader:raise ValueError('Pinned selector contract not recognized')
 from old_slots import metadata
 return dict(selector_game_id='AllLuckyClover',variants=list(VARIANTS),loader_sha256=LOADER_SHA256,source_sha256=BUNDLE_SHA256,client_version=VERSION,old_slots=metadata(source))

def variant_plan(initial,variant,bundle_raw):
 """Select the actual native API, preserving total stake versus line stake."""
 if variant not in VARIANTS or hashlib.sha256(bundle_raw).hexdigest()!=BUNDLE_SHA256:raise ValueError('Selected slot/source identity differs')
 source=bundle_raw.decode('utf8')
 if initial.get('api_version')!='2':
  from old_slots import metadata,plan
  meta=metadata(source);modes=plan(initial,meta)
 else:
  tokens=['Ye.isApi2="2"===e.api_version','h={command:"spin"},p={};if(Ye.isApi2)i?p.bonus=!0:t||n||(p.bet=e),t&&(h.command="freespin"),n&&(h.command="respin")','Object.keys(p).length&&(h.options=p)','Me=!!e.options.line_bets','initialAvailableBets=Me&&e.options.line_bets?e.options.line_bets.map((t=>t*e.options.lines.length)):e.options.available_bets']
  if not all(token in source for token in tokens):raise ValueError('API2 total native bet branch not proved')
  o=initial.get('options',{});currency=o.get('currency',{});balance=initial.get('balance',{});flow=initial.get('flow',{});bets=o.get('available_bets')
  if currency.get('code')!='FUN' or currency.get('subunits')!=100 or type(balance.get('wallet')) is not int or balance['wallet']<0 or type(balance.get('game')) is not int or balance['game']!=0:raise ValueError('Actual API2 variant native FUN initialization required')
  if flow.get('state')!='ready' or flow.get('command')!='init' or flow.get('round_id') is not None or set(flow.get('available_actions',[]))!={'init','spin'}:raise ValueError('Variant initialization has pending native actions')
  if not isinstance(bets,list) or not bets or any(type(b) is not int or b<=0 for b in bets) or o.get('line_bets') or len(o.get('lines',[]))!=int(variant.removeprefix('AllLuckyClover')):raise ValueError('Actual variant total native stakes/line count not proved')
  if o.get('feature_options') or o.get('buy_feature_value'):raise ValueError('Additional variant feature contract requires review')
  meta=dict(protocol='legacy-api2-slots',source_verified=True,source_sha256=BUNDLE_SHA256,api2_native_bet_verified=True,native_bet_contract='API version 2 sends options.bet=UI total stake from available_bets unchanged; lines do not scale cost',continuation_whitelist=['freespin','respin'],verification_limit='Only actual API2 initialization normal mode; no unobserved purchase or gamble choices declared')
  from run_demo_qa import modes_from_init
  modes=modes_from_init(initial,meta)
  expected=[dict(name='normal',command='spin',options={'bet':min(bets)},cost_native=min(bets))]
  if modes!=expected:raise ValueError('API2 native normal plan differs from proved source')
 meta.update(parent_selector_game_id='AllLuckyClover',selected_variant=variant,selector_source_sha256=BUNDLE_SHA256)
 return meta,modes

def prepare_received(checkpoint,*,received_request,selector_initial,fresh_suite_owned,fetch_source,gate):
 """Rebuild one received init offline plus fresh static GETs; no launch/init replay.

 The parent must restore its original cookie jar separately and retain both raw
 inputs unchanged. This function cannot send selector or API requests.
 """
 if fresh_suite_owned is not True or checkpoint.get('stage')!='variant_init_received':raise ValueError('Own already received variant init checkpoint required')
 payload=checkpoint['payload'];variant=payload['variant'];cfg=copy.deepcopy(payload['bootstrap']);initial=payload['response'];record=received_request
 if variant not in VARIANTS or record.get('status')!='received' or record.get('method')!='POST' or record.get('http_status')!=200 or record.get('response')!=initial or record.get('url')!=cfg.get('api'):raise ValueError('Private received init receipt/context differs')
 try:request=json.loads(record['body'])
 except (ValueError,TypeError,KeyError):raise ValueError('Received native init request missing') from None
 if request!={'command':'init'}:raise ValueError('Received receipt is not init-only')
 base=cfg.get('resources_root_path');uninitialized=copy.deepcopy(cfg);uninitialized['resources_path']=base;validate_config(uninitialized,variant)
 if cfg.get('resources_path')!=base.rstrip('/')+'/'+VERSION or cfg.get('game_bundle_source')!=base.rstrip('/')+'/'+VERSION+'/bundle.js':raise ValueError('Received initialized source route differs')
 gate.check();loader=fetch_source(base.rstrip('/')+'/loader.js');gate.check();bundle=fetch_source(cfg['game_bundle_source']);source_contract(loader,bundle)
 meta,modes=variant_plan(initial,variant,bundle)
 return PreparedVariant(variant,cfg,copy.deepcopy(initial),meta,modes,digest_json(selector_initial),payload['last_launch_epoch'])

class VariantGate:
 """Borrow the parent's existing runner lock, or own one outside its runner.

 last_launch_epoch is the parent's persisted latest game/variant launch time.
 A private checkpoint before GET must persist each new reserved epoch so a
 restarted executor cannot reset the suite-wide one-minute launch limit.
 """
 def __init__(self,root,*,last_launch_epoch,lock_handle=None,maintenance_authorized=False,clock=time.time,sleeper=time.sleep):
  if type(last_launch_epoch) not in (int,float) or not math.isfinite(last_launch_epoch):raise ValueError('Prior suite launch timestamp required')
  self.root=Path(root).resolve();self.last_launch_epoch=last_launch_epoch;self.handle=lock_handle;self.owns=False;self.active=False;self.clock=clock;self.sleeper=sleeper;self.maintenance_authorized=maintenance_authorized is True
 def __enter__(self):
  if self.handle is None:
   from checkpoint_guard import acquire
   self.handle=acquire(self.root/'runner.lock');self.owns=True
  if self.handle.closed or Path(self.handle.name).resolve()!=self.root/'runner.lock':raise RuntimeError('Parent runner.lock handle required')
  self.active=True;return self
 def __exit__(self,*args):
  self.active=False
  if self.owns and self.handle is not None:self.handle.close();self.handle=None
 def check(self):
  if not self.active or self.handle is None or self.handle.closed:raise RuntimeError('Variant preparation requires active runner.lock')
  stop=self.root/'STOP'
  if stop.exists():
   value=stop.read_text(encoding='utf8').strip()
   if value!='CONTINUE' and not (self.maintenance_authorized and value=='CHECKPOINT_MAINTENANCE'):raise RuntimeError('STOP pauses selector/init requests')
 def reserve(self):
  self.check()
  while True:
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now):raise ValueError('Invalid suite clock')
   remaining=60-(now-self.last_launch_epoch)
   if remaining<=0:break
   self.sleeper(min(1,remaining));self.check()
  self.last_launch_epoch=now;return now

@dataclass(repr=False)
class PreparedVariant:
 game_id:str
 bootstrap:dict
 initial:dict
 metadata:dict
 modes:list
 selector_initial_sha256:str
 started_epoch:float
 def public_record(self):
  return dict(game_id=self.game_id,parent_selector_game_id='AllLuckyClover',status='variant_init_source_prepared_no_wagers',protocol=self.metadata['protocol'],initial_sha256=digest_json(self.initial),selector_initial_sha256=self.selector_initial_sha256,protocol_metadata=self.metadata,modes=copy.deepcopy(self.modes),started_epoch=self.started_epoch,gameplay_calls=0)

class SelectorPreparer:
 def __init__(self,cfg,selector_initial,*,fresh_suite_owned,fetch_source,request_json,private_checkpoint,gate):
  if fresh_suite_owned is not True:raise ValueError('A newly launched suite-owned FUN selector is required; HAR sessions are forbidden')
  self.selector_bootstrap=validate_config(cfg,'AllLuckyClover');self.current_config=copy.deepcopy(self.selector_bootstrap);self.selector_initial=copy.deepcopy(selector_initial);self.fetch_source=fetch_source;self.request_json=request_json;self.checkpoint=private_checkpoint;self.gate=gate;self.contract=None;self.halted=False;self.selected=set()
 def _fetch(self,url):
  self.gate.check();official_url(url)
  try:raw=self.fetch_source(url)
  except Exception:raise RuntimeError('Static source fetch failed; private checkpoint requires review') from None
  if not isinstance(raw,bytes):raise ValueError('Fresh source callback must return original bytes')
  return raw
 def _headers(self,cfg):return {'Content-Type':'application/json',cfg['csrfTokenHeaderName']:cfg['csrfTokenHeaderValue']}
 def _request(self,method,url,cfg,body):
  self.gate.check();official_url(url)
  try:return self.request_json(method,url,self._headers(cfg),body)
  except Exception:raise RuntimeError('Selector/init transport outcome requires private review; no retry') from None
 def prepare(self,variant):
  if variant not in VARIANTS:raise ValueError('Variant not present in source selector registry')
  if self.halted or variant in self.selected:raise RuntimeError('Variant attempt already consumed or interrupted; review private evidence before a fresh executor')
  self.gate.check();started=self.gate.reserve()
  self.checkpoint('before_variant_get',dict(variant=variant,last_launch_epoch=started,bootstrap=copy.deepcopy(self.current_config),original_selector_bootstrap=copy.deepcopy(self.selector_bootstrap),original_selector_initial=copy.deepcopy(self.selector_initial)))
  try:
   if self.contract is None:
    base=self.selector_bootstrap['resources_path'].rstrip('/')
    self.contract=source_contract(self._fetch(base+'/loader.js'),self._fetch(base+'/'+VERSION+'/bundle.js'))
   old=self.current_config;separator='&' if old['lobby_launch_url'].find('?')>0 else '?'
   url=old['lobby_launch_url']+separator+'game='+quote(variant,safe='')+'&from='+quote(old['identifier'],safe='')
   self.selected.add(variant)
   returned=self._request('GET',url,old,None)
   self.checkpoint('variant_bootstrap_received',dict(variant=variant,response=copy.deepcopy(returned),last_launch_epoch=started))
   cfg=validate_config(returned,variant)
   # Source replaces the complete casino options, then applies the SAME
   # pinned selector initializer. No previous API/CSRF fields are merged.
   self.current_config=copy.deepcopy(cfg)
   base=cfg['resources_path'].rstrip('/');bundle_url=base+'/'+VERSION+'/bundle.js'
   raw=self._fetch(bundle_url)
   if hashlib.sha256(raw).hexdigest()!=BUNDLE_SHA256:raise ValueError('Actual variant source differs from pinned selector client')
   initialized_cfg=copy.deepcopy(cfg);initialized_cfg['resources_root_path']=cfg['resources_path'];initialized_cfg['resources_path']=base+'/'+VERSION;initialized_cfg['game_bundle_source']=bundle_url
   body=json.dumps({'command':'init'},separators=(',',':')).encode()
   self.checkpoint('before_variant_init',dict(variant=variant,bootstrap=copy.deepcopy(initialized_cfg),request={'command':'init'},source_sha256=BUNDLE_SHA256,last_launch_epoch=started))
   initial=self._request('POST',cfg['api'],cfg,body)
   self.checkpoint('variant_init_received',dict(variant=variant,response=copy.deepcopy(initial),bootstrap=copy.deepcopy(initialized_cfg),last_launch_epoch=started))
   try:meta,modes=variant_plan(initial,variant,raw)
   except (KeyError,TypeError,ValueError,AttributeError):raise ValueError('Actual selected-variant init does not prove a source-native slot protocol; no wager prepared') from None
   result=PreparedVariant(variant,initialized_cfg,copy.deepcopy(initial),meta,modes,digest_json(self.selector_initial),started)
   self.checkpoint('variant_prepared',dict(variant=variant,public_record=result.public_record(),bootstrap=copy.deepcopy(initialized_cfg),response=copy.deepcopy(initial)))
   return result
  except Exception:
   self.halted=True
   raise
