"""Observed BGaming Hyperhive public FUN JSON-RPC transport. No replay or balance edits."""
import json,re,time,uuid,copy,hashlib,urllib.request,urllib.error
from fractions import Fraction
from urllib.parse import urlsplit
from pathlib import Path
from analyze import Sanitizer
ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);temporary=p.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(p)
def timestamp():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
class InitEnvelope(dict):pass

def native_script_entries(frontend):
 entries=[]
 for script in re.findall(r'<script[^>]+src=[\"\x27]([^\"\x27]+)',frontend):
  u=urlsplit(script)
  if u.netloc or u.scheme or u.fragment or '..' in u.path.split('/') or not re.fullmatch(r'(?:\./|/)?[A-Za-z0-9_./-]+\.js',u.path):continue
  if u.query and not re.fullmatch(r'(?:[a-f0-9]{8,64}|(?:v|ver|version|hash)=[A-Za-z0-9_.-]+)',u.query):continue
  entries.append(script)
 return entries

def parse_metadata(definitions,client,source,allowed):
 d=definitions['engine']['definition'];features={};unresolved=[]
 ante=[]
 for block in re.findall(r'getPurchasedFeatureConfig\(\)\{return\{([^}]+)\}\}',source):
  ante+=re.findall(r'ante:[A-Za-z_$][\w$]*\.([\w$]+)',block)
 buy=[]
 for block in re.findall(r'getBuyFeaturePurchasedValues\(\)\{return\[([^\]]+)\]\}',source):buy+=re.findall(r'[A-Za-z_$][\w$]*\.([\w$]+)',block)
 for feature in dict.fromkeys(ante):
  if feature in allowed and isinstance(d.get('anteBetStake'),(int,float)):features[feature]=str(d['anteBetStake'])
  else:unresolved.append('ante:'+feature)
 keys={'freespin_buy':('featureBuyMulFreespin','buyBonusStake'),'bonus_buy':('featureBuyMulRespin','buyBonusStake'),'high_freespin_buy':('superBuyBonusStake',),'buy_bonus':('buyBonusStake',)}
 for feature in dict.fromkeys(buy):
  factor=next((d[k] for k in keys.get(feature,()) if isinstance(d.get(k),(int,float))),None)
  if feature in allowed and factor is not None and factor>0:features[feature]=str(factor)
  else:unresolved.append('buy:'+feature)
 if d.get('anteBetStake',1)>1 and not ante:unresolved.append('ante mapping not found')
 if any(d.get(k) for k in ['buyBonusStake','superBuyBonusStake','featureBuyMulRespin','featureBuyMulFreespin']) and not buy:unresolved.append('buy mapping not found')
 choices={}
 for enum_name,member in re.findall(r'params:\{choice:([A-Za-z_$][\w$]*)\.(Collect|Gamble)\}',source):
  start=source.find('var '+enum_name+';');end=source.find('}('+enum_name+'||',start)
  if start>=0 and end>start:
   m=re.search(r'\.'+member+r'=(\d+)',source[start:end])
   if m:choices[member.lower()]=int(m[1])
 return dict(protocol='jsonrpc',features=features,unresolved=unresolved,choices=choices,client_version=client.get('Version'),definitions_game_version=d.get('gameVersion'),source_sha256=hashlib.sha256(source.encode()).hexdigest(),feature_mapping_evidence='Game-specific getPurchasedFeatureConfig/getBuyFeaturePurchasedValues, filtered by init whitelist; definition prices are total stake factors.')

def plan_modes(initial,metadata):
 if metadata.get('engine')=='four-modern-slots':
  from four_modern_slots import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='final-rpc-pair':
  from final_rpc_pair import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='rpc-extra':
  from rpc_extra import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='flat-rpc':
  from flat_rpc import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='lucky-birds':
  from lucky_birds import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='product-round':
  from product_round_rpc import plan
  return plan(initial,metadata)
 if metadata.get('engine')=='cocos':
  from cocos_adapter import plan
  return plan(initial,metadata)
 r=initial['result'];attrs=r['currency_attributes'];assert r['currency']=='FUN' and attrs['code']=='FUN' and attrs['subunits']==100 and attrs['exponent']==2
 if r.get('freebets'):raise ValueError('Promotional freebet state needs separate review')
 if r.get('state') is not None:raise ValueError('Existing open RPC state; no new round allowed')
 bet=min(r['config']['bet_limits']);modes=[]
 if metadata.get('engine')=='oga-classic':
  for variant in [dict(name='normal',feature=None,factor='1',custom_params=metadata['normal_custom_params'])]+metadata['variants']:
   price=Fraction(bet)*Fraction(variant['factor'])
   if price.denominator!=1:raise ValueError('Unverified classic OGA price')
   modes.append(dict(name=variant['name'],protocol='jsonrpc',feature=variant['feature'],bet_native=bet,cost_native=int(price),policy='collect',custom_params=variant['custom_params']))
  if metadata.get('star_choices_verified'):
   from star_choices import expand
   return expand(modes)
  return modes
 for feature,factor in [(None,'1')]+list(metadata['features'].items()):
  price=Fraction(bet)*Fraction(factor)
  if price.denominator!=1 or price<=0:raise ValueError('Unverified fractional RPC price')
  name=feature or 'normal'
  modes.append(dict(name=name,protocol='jsonrpc',feature=feature,bet_native=bet,cost_native=int(price),policy='collect'))
  modes.append(dict(name=name+'/gamble_once',protocol='jsonrpc',feature=feature,bet_native=bet,cost_native=int(price),policy='gamble_once',conditional_gamble=True))
 return modes

class Hyperhive:
 def __init__(self,parent,cfg):
  self.parent=parent;self.cfg=cfg;u=urlsplit(parent.page);self.origin=u.scheme+'://'+u.netloc
  if u.scheme!='https' or not (u.hostname or '').endswith('.demo.bgaming-network.com'):raise ValueError('Invalid Hyperhive demo origin')
  self.endpoint=self.origin+'/api';self.token=cfg['play_token'];self.last=None;self.initial=None;self.raw_events=[];self.offers=set();self.metadata={};self.status='new';self.last_response=None
  self.private=getattr(parent,'private_session_path',PRIVATE/'hyperhive'/(parent.game['game_id']+'.session.json'))
 def checkpoint(self,status,request=None):
  self.status=status;cookies=[]
  for h in self.parent.opener.handlers:
   if isinstance(h,urllib.request.HTTPCookieProcessor):cookies=[dict(name=c.name,value=c.value,domain=c.domain,path=c.path,secure=c.secure,expires=c.expires) for c in h.cookiejar]
  save(self.private,dict(fresh_demo=True,game_id=self.parent.game['game_id'],endpoint=self.endpoint,token=self.token,last_result=self.last,initial=self.initial,last_request=request,last_response=self.last_response,status=status,events=self.raw_events,cookies=cookies,metadata=self.metadata,updated_at=timestamp()))
 def request(self,method,req=None):
  params={'token':self.token}
  if req is not None:params['req']=req
  if method=='play' and not (self.parent.game['game_id']=='JokerVsJoker' and self.metadata.get('omit_state_lock') is True):params['state_lock']=self.last.get('state_lock','')
  q=dict(id=str(uuid.uuid4()),jsonrpc='2.0',method=method,params=params);self.checkpoint('sending',q)
  time.sleep(.5)
  headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json','Accept':'application/json','Origin':self.origin,'Referer':self.origin+'/'}
  try:
   with self.parent.opener.open(urllib.request.Request(self.endpoint,data=json.dumps(q).encode(),headers=headers),timeout=45) as r:raw=r.read();status=r.status
  except urllib.error.HTTPError as e:raw=e.read();status=e.code
  except Exception as e:self.checkpoint('uncertain',q);raise RuntimeError('Uncertain RPC response; no retry') from None
  try:r=json.loads(raw)
  except ValueError:r={'body_format':'non_json','bytes':len(raw)}
  event=dict(time=timestamp(),request=q,response=r,status=status,response_sha256=hashlib.sha256(raw).hexdigest());self.raw_events.append(event);self.last_response=r
  clean=self.parent.clean;public=copy.deepcopy(event);public['request']['id']='rpc-'+str(len(self.raw_events))
  if 'id' in public['response']:public['response']['id']='rpc-'+str(len(self.raw_events))
  if self.parent.game['game_id']=='YommiRush' and self.metadata.get('engine')=='final-rpc-pair':
   result=public['response'].get('result',{})
   for field,alias in [('round','round_id'),('step','last_action_id')]:
    if result.get(field) is not None:result[field]=clean.clean(result[field],alias)
  round_data=public['response'].get('result',{}).get('resp',{}).get('round',{})
  if 'id' in round_data:round_data['id']=clean.clean(round_data['id'],'round_id')
  self.parent.events.append(clean.clean(public))
  if status!=200 or 'result' not in r:self.checkpoint('received_error',q);raise RuntimeError('RPC rejected; inspect preserved response')
  if method in ('init','play'):self.last=r['result']
  self.checkpoint('received',q);return r
 def fetch(self,route):
  try:
   with self.parent.opener.open(urllib.request.Request(self.origin+route,headers={'User-Agent':'Mozilla/5.0','Referer':self.origin+'/'}),timeout=40) as r:return r.read()
  except urllib.error.HTTPError as error:
   save(ROOT/'protocols'/(self.parent.game['game_id']+'.fetch-error.json'),dict(route=urlsplit(route).path,status=error.code,updated_at=timestamp()))
   raise ValueError('Public metadata HTTP '+str(error.code)+' at '+urlsplit(route).path) from None
 def initialize(self):
  from urllib.parse import quote
  frontend=self.fetch('/?token='+quote(self.token,safe='')).decode('utf8')
  cocos='src/import-map.json' in frontend and 'System.import' in frontend
  initial=self.request('init',{} if cocos else None);self.initial=initial;self.checkpoint('received')
  attrs=initial['result']['currency_attributes'];assert attrs['code']=='FUN' and attrs['subunits']==100 and initial['result']['currency']=='FUN'
  custom_entries=native_script_entries(frontend)
  if self.parent.game['game_id']=='SweetSamurai':
   from flat_rpc import metadata
   route='/assets/main/index.js';source=self.fetch(route).decode('utf8');self.metadata=metadata(source);self.metadata['entry_path']=route;self.parent.protocol='jsonrpc-flat'
  elif self.parent.game['game_id']=='LuckyBirds':
   from lucky_birds import metadata
   entries=[s for s in custom_entries if re.fullmatch(r'(?:\./|/)?assets/index-[A-Za-z0-9_-]+\.js',urlsplit(s).path)]
   if len(entries)!=1:raise ValueError('Lucky Birds module entry not uniquely recognized')
   route='/'+entries[0].lstrip('./');source=self.fetch(route).decode('utf8');self.metadata=metadata(source);self.metadata['entry_path']=route;self.parent.protocol='jsonrpc-lucky-birds'
  elif self.parent.game['game_id'] in ['CatsLoveYummy','RedHotChilliChickens','MysticReels','ChickenFire']:
   from four_modern_slots import load_metadata
   self.metadata=load_metadata(self.parent.game['game_id'],frontend,self.fetch,initial['result']['config'].get('purchased_features',[]));self.parent.protocol='jsonrpc-four-modern-slots'
  elif self.parent.game['game_id'] in ['YommiRush','JokerVsJoker']:
   from final_rpc_pair import metadata
   gid=self.parent.game['game_id'];proof=json.loads((ROOT/'protocols'/(gid+'.final-pair-prepared.json')).read_text(encoding='utf8'));route=proof['entry_path']
   if route not in ['/'+urlsplit(entry).path.lstrip('./') for entry in custom_entries]:raise ValueError('Fresh final-pair source entry differs')
   self.metadata=metadata(gid,self.fetch(route).decode('utf8'),initial['result']['config'].get('purchased_features',[]));self.metadata['entry_path']=route;self.parent.protocol='jsonrpc-final-pair'
  elif self.parent.game['game_id'] in ['Robospin','KeepersOfTheSecret7rst','GrandPatron7rst','BigBucksSaloon','ClashofGodsAnubisvsHades','AztecsClawWildDice']:
   from rpc_source_pins import load_metadata
   self.metadata=load_metadata(self.parent.game['game_id'],frontend,self.fetch,initial['result']['config'].get('purchased_features',[]));self.parent.protocol='jsonrpc-rpc-extra'
  elif self.parent.game['game_id'] in ['RecycleRiches','BlackbeardsBounty','BlazingFirepots','JungleQueen','SugarMix','TreasureExplorer','ZeusGoesWild']:
   from rpc_extra import metadata
   gid=self.parent.game['game_id']
   if gid=='BlackbeardsBounty':entries=[s for s in custom_entries if re.fullmatch(r'(?:\./|/)?assets/index-[A-Za-z0-9_-]+\.js',urlsplit(s).path)]
   elif gid in ['JungleQueen','ZeusGoesWild']:entries=[s for s in custom_entries if urlsplit(s).path.lstrip('./')=='bundle.js']
   elif gid in ['SugarMix','TreasureExplorer']:entries=[s for s in custom_entries if re.fullmatch(r'main\.[a-f0-9]+\.js',urlsplit(s).path.lstrip('./'))]
   else:entries=[s for s in custom_entries if urlsplit(s).path.lstrip('./')=='main.js']
   if len(entries)!=1:raise ValueError('Custom RPC source entry not uniquely recognized')
   route='/'+entries[0].lstrip('./');source=self.fetch(route).decode('utf8');self.metadata=metadata(source,initial['result']['config'].get('purchased_features',[]));self.metadata['entry_path']=urlsplit(route).path;self.parent.protocol='jsonrpc-rpc-extra'
  elif cocos:
   from cocos_metadata import load_metadata
   self.metadata=load_metadata(self.fetch);self.parent.protocol='jsonrpc-cocos'
  elif len(custom_entries)==1:
   import importlib,product_round_rpc
   importlib.reload(product_round_rpc)
   route='/'+custom_entries[0].lstrip('./');source=self.fetch(route).decode('utf8');self.metadata=product_round_rpc.metadata(source,initial['result']['config'].get('purchased_features',[]));self.metadata['entry_path']=route;self.parent.protocol='jsonrpc-product-round'
  else:
   defs_raw=self.fetch('/game/media/definitions.json');client_raw=self.fetch('/game/media/clientConfig.json');source_raw=self.fetch('/game/game.min.js')
   defs=json.loads(defs_raw);client=json.loads(client_raw);source=source_raw.decode('utf8');self.metadata=parse_metadata(defs,client,source,initial['result']['config'].get('purchased_features',[]));self.metadata.update(definitions_url=self.origin+'/game/media/definitions.json',definitions_sha256=hashlib.sha256(defs_raw).hexdigest(),client_config_sha256=hashlib.sha256(client_raw).hexdigest())
   classic_client=self.fetch('/client.min.js').decode('utf8')
   if 'formattedRequest.params.action=' in classic_client:
    import importlib,oga_classic
    importlib.reload(oga_classic)
    integration=self.fetch('/game/integration.min.js').decode('utf8');self.metadata.update(oga_classic.parse(defs,source,integration,classic_client))
    if self.parent.game['game_id']=='StarTrekNextGen':
     from star_choices import metadata as star_metadata
     self.metadata.update(star_metadata(source,integration))
  save(ROOT/'protocols'/(self.parent.game['game_id']+'.json'),self.metadata);self.checkpoint('received')
  self.parent.bootstrap.update(protocol=self.parent.protocol,client_version=self.metadata.get('client_version'),definitions_game_version=self.metadata.get('definitions_game_version'));self.parent.protocol_metadata=self.metadata
  envelope=InitEnvelope(initial);envelope.protocol_metadata=self.metadata;return envelope
 def run_mode(self,mode,initial):
  if mode.get('protocol')=='jsonrpc-four-modern-slots':
   from four_modern_slots import run
   return run(self,mode)
  if mode.get('protocol')=='jsonrpc-final-pair':
   from final_rpc_pair import run
   return run(self,mode)
  if mode.get('protocol')=='jsonrpc-rpc-extra':
   from rpc_extra import run
   return run(self,mode)
  if getattr(self,'metadata',{}).get('engine')=='flat-rpc':
   from flat_rpc import run
   return run(self,mode)
  if getattr(self,'metadata',{}).get('engine')=='lucky-birds':
   from lucky_birds import run
   return run(self,mode)
  if mode.get('protocol')=='jsonrpc-product-round':
   from product_round_rpc import run
   return run(self,mode)
  if mode.get('protocol')=='jsonrpc-cocos':
   from cocos_adapter import run
   return run(self,mode)
  feature=mode['feature'];conditional=mode.get('conditional_gamble',False)
  if conditional and feature not in self.offers:return dict(mode=mode,status='not_applicable',reason='Gamble not offered in the preceding observed mode',network_calls=0)
  if self.last.get('final') is False or (self.last.get('state') is not None and 'final' not in self.last):raise RuntimeError('Open RPC round; no new purchase permitted')
  before=self.last['balance'];cost=mode['cost_native'];bet=mode['bet_native'];start=len(self.parent.events);total_win=Fraction(0);choices=[];offered=[];gambled=False
  if before<cost:return dict(mode=mode,status='insufficient_demo_balance')
  req=dict(bet=bet,bet_type='bet',custom_req={'exponent':2})
  if self.metadata.get('engine')=='oga-classic':
   from oga_classic import customize
   req['custom_req']=customize(self.metadata,mode,bet,'spin',True)
  if feature:req['purchased_feature']=feature
  r=self.request('play',req)['result'];g=r.get('resp',{}).get('engine',{}).get('gamestate',{})
  if 'totalStake' in g:
   ok=Fraction(str(g['totalStake']))==cost;self.parent.money_checks.append(dict(kind='initial_stake',expected=cost,actual=g['totalStake'],ok=ok))
   if not ok:raise RuntimeError('RPC purchase price mismatch; round retained')
  for _ in range(500):
   win=r.get('resp',{}).get('win')
   if not isinstance(win,(int,float)):raise RuntimeError('RPC win schema unknown')
   total_win+=Fraction(str(win));g=r.get('resp',{}).get('engine',{}).get('gamestate',{});action=g.get('triggeringDetails',{}).get('nextAction')
   if isinstance(action,list):offered+=action
   if r.get('final') is True:break
   if self.metadata.get('star_choices_verified'):
    from star_choices import next_request
    request=next_request(r,mode,self.metadata)
    if request['custom_req']['action']=='fs_choice':choices.append('fs_choice:'+str(request['custom_req']['choice']))
    r=self.request('play',request)['result'];continue
   request=dict(bet=bet,bet_type='bet',custom_req={'exponent':2})
   if isinstance(action,list) and set(action)<= {'gamble','collect'} and action:
    if 'gamble' in action:self.offers.add(feature)
    name='gamble' if mode['policy']=='gamble_once' and not gambled and 'gamble' in action else 'collect' if 'collect' in action else None
    if name is None or name not in self.metadata['choices']:raise RuntimeError('RPC choice mapping needs review')
    request['custom_req']['choice']=self.metadata['choices'][name];choices.append(name);gambled=gambled or name=='gamble'
   elif not isinstance(action,str) or (action not in ('freespin','respin','jackpot','bonus','cascade','spin','cascadefg','extra_bet_hold') and action not in self.metadata.get('classic_continuations',{})):raise RuntimeError('Unknown RPC continuation; round retained for review')
   if self.metadata.get('engine')=='oga-classic':
    from oga_classic import customize
    request['custom_req']=customize(self.metadata,mode,bet,action,False)
   r=self.request('play',request)['result']
  else:raise RuntimeError('RPC continuation limit; unresolved state retained')
  expected=Fraction(str(before))-cost+total_win;actual=r['balance'];ok=expected==Fraction(str(actual));self.parent.money_checks.append(dict(kind='round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=actual,ok=ok))
  if not ok:raise RuntimeError('RPC round balance mismatch; inspect native evidence')
  status='branch_not_observed' if conditional and 'gamble' not in choices else 'closed'
  return dict(mode=mode,status=status,first_event=start,last_event=len(self.parent.events)-1,final_balance=actual,final_state='final',win_native=int(total_win) if total_win.denominator==1 else float(total_win),win_ratio=[total_win.numerator,total_win.denominator],choices_taken=choices,choices_offered=sorted(set(offered)))
