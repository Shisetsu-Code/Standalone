"""Public FUN demos only. Sequential QA; no replay, real-money accounts or balance edits."""
import json,re,time,uuid,hashlib,urllib.request,http.cookiejar,urllib.error,argparse
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit,urljoin
import importlib
import analyze as sanitation
Sanitizer=importlib.reload(sanitation).Sanitizer
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'live'
PRIVATE=ROOT.parent.parent/'bgaming-private-chat4'
def save(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def now():return datetime.now(timezone.utc).isoformat()
class NativeInit(dict):pass
def retain_launch_evidence(report,demo):
 if getattr(demo,'provider_state_observations',None):report['provider_state_observations']=demo.provider_state_observations
 if hasattr(demo,'bootstrap'):report['bootstrap']=demo.bootstrap
 report['protocol']=getattr(demo,'protocol','legacy' if hasattr(demo,'api') else 'unknown')
 if hasattr(demo,'protocol_metadata'):report['protocol_metadata']=demo.protocol_metadata
def trusted(url):
 u=urlsplit(url)
 if u.scheme!='https' or not (u.hostname=='demo.bgaming-network.com' or (u.hostname or '').endswith('.demo.bgaming-network.com')):raise ValueError('Non official public demo endpoint rejected')
 return url
class Demo:
 def __init__(self,game):
  self.game=game;self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));self.clean=Sanitizer();self.events=[];self.series=int(time.time()*1000);self.prev=None;self.money_checks=[];self.protocol_metadata={}
 def launch(self):
  url=trusted(self.game['demo_url'])
  with self.opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as r:
   trusted(r.url);text=r.read().decode('utf8');self.page=r.url
  m=re.search(r'window\.__OPTIONS__\s*=\s*',text)
  if not m:
   PRIVATE.mkdir(parents=True,exist_ok=True);(PRIVATE/(self.game['game_id']+'.bootstrap.html')).write_text(text,encoding='utf8')
   scripts=[]
   for source in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',text):
    link=urlsplit(urljoin(self.page,source))
    if link.scheme=='https' and link.hostname and (link.hostname.endswith('.bgaming-network.com') or link.hostname=='bgaming.com'):
     scripts.append(dict(host=link.hostname,path=re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27,}','{id}',link.path)))
   save(ROOT/'bootstrap'/(self.game['game_id']+'.json'),dict(game_id=self.game['game_id'],page_host=urlsplit(self.page).hostname,page_path=urlsplit(self.page).path,scripts=scripts,engine='unrecognized'))
   raise ValueError('Bootstrap options not recognized; private HTML and public script index preserved')
  cfg,_=json.JSONDecoder().raw_decode(text[m.end():])
  if cfg.get('currency')!='FUN' or cfg.get('server_id')!='demo' or cfg.get('identifier')!=self.game['game_id']:raise ValueError('Demo identity/currency/server validation failed')
  self.opener.classic_casino=bool(re.search(r'<script[^>]+src=[\"\x27]https://cdn\.bgaming-network\.com/html/casino\.min\.js[\"\x27]',text));self.opener.classic_version=cfg.get('version')
  self.bootstrap=dict(identifier=cfg.get('identifier'),currency=cfg.get('currency'),server_id=cfg.get('server_id'),version=cfg.get('version'))
  bundle=cfg.get('game_bundle_source')
  if isinstance(bundle,str) and urlsplit(bundle).hostname=='cdn.bgaming-network.com' and not urlsplit(bundle).query:self.bootstrap['game_bundle_source']=bundle
  if urlsplit(self.page).path=='/hyperhive':
   import hyperhive_adapter
   importlib.reload(hyperhive_adapter)
   self.protocol='jsonrpc';self.hyper=hyperhive_adapter.Hyperhive(self,cfg);return self.hyper.initialize()
  self.api=trusted(cfg['api']);self.csrf_name=cfg['csrfTokenHeaderName'];self.csrf_value=cfg['csrfTokenHeaderValue']
  initial=self.call('init');fm=initial.get('options',{}).get('feature_options',{}).get('feature_multipliers',{})
  import legacy_metadata
  importlib.reload(legacy_metadata)
  if self.game['game_id'] in ['BlackjackPro','MultihandBlackjack','ClassicMultihandBlackjack','MultihandBlackjackPro2','SurrenderMultihandBlackjack']:
   self.protocol_metadata.update(legacy_metadata.prove_blackjack(self.game['game_id'],self.opener));self.protocol='blackjack-extra';envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['InfinityPull','ChickenRush2','PenaltyDuel','PenaltyDuelWithJulioCesar','FishingTime','ElementsOfPower','JogoDoBicho','TileMaster']:
   self.protocol_metadata.update(legacy_metadata.prove_native_modes_extra(self.game['game_id'],self.opener));self.protocol=self.protocol_metadata['protocol'];envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['RocketDice','RocketDiceXY','MineGems','FortuneRedPackets','Minesweeper','MinesweeperXY']:
   self.protocol_metadata.update(legacy_metadata.prove_native_tables(self.game['game_id'],self.opener));self.protocol=self.protocol_metadata['protocol'];envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='ThreeKingsScratch':
   self.protocol_metadata.update(legacy_metadata.prove_scratch_packs(self.game['game_id'],self.opener));envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='RoyalRoulette500X':
   self.protocol='royal-roulette';self.protocol_metadata.update(legacy_metadata.prove_royal_roulette(self.game['game_id'],self.opener));envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['AmericanRoulette','EuropeanRoulette','FrenchRoulette']:
   self.protocol='classic-roulette';self.protocol_metadata.update(legacy_metadata.prove_classic_roulette(self.game['game_id'],self.opener));envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['DiceClash','StreetPower','FortuneSpin']:
   self.protocol='native-play-modes';self.protocol_metadata.update(legacy_metadata.prove_native_play(self.game['game_id'],self.opener));envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='Limbo':
   self.protocol='legacy-limbo';self.protocol_metadata.update(legacy_metadata.prove_limbo(self.game['game_id'],self.opener));envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='CatsSoup':self.protocol_metadata.update(legacy_metadata.prove_cats_choices(self.game['game_id'],self.opener))
  if self.game['game_id'] in ['BurningChilliX','RoyalFruitsMultiLines','WildTiger','FishingClub','WinterFishingClub']:
   self.protocol_metadata.update(legacy_metadata.prove_line_counts(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['DiamondOfJungle','DiscoParty']:
   self.protocol_metadata.update(legacy_metadata.prove_volatility(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='BigAtlantisFrenzy':
   self.protocol_metadata.update(legacy_metadata.prove_indexed_rows(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['HeadsTails','HeadsTailsXY']:
   self.protocol='classic-heads';self.protocol_metadata.update(legacy_metadata.prove_classic_heads(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['MonsterHunt','AlohaKingElvis','CatchTheGoldHoldAndWin']:
   self.protocol_metadata.update(legacy_metadata.prove_freespin_types(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['Maneki88Fortunes','Maneki88Gold']:
   self.protocol_metadata.update(legacy_metadata.prove_gold_symbols(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id'] in ['Plinko','EasterPlinko','PlinkoXY']:
   self.protocol='legacy-plinko';self.protocol_metadata.update(legacy_metadata.prove_classic_plinko(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if initial.get('api_version')!='2' and initial.get('options',{}).get('line_bets') and type(initial.get('balance')) is int:
   self.protocol='legacy-v1-slots';self.protocol_metadata.update(legacy_metadata.prove_old_slot(self.game['game_id'],self.opener))
   pending=[k for k in ['buy_feature_value','feature_options'] if initial['options'].get(k) and not (k=='buy_feature_value' and self.protocol_metadata.get('v1_buy_feature_verified'))]
   if pending:self.protocol_metadata['unresolved']=[dict(kind=k,reason='Native v1 feature advertised; purchase and bonus continuation contract pending') for k in pending]
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.game['game_id']=='AliceWonderLuck':self.protocol_metadata.update(legacy_metadata.prove_alice_choices(self.game['game_id'],self.opener))
  if 'default_seed' in initial.get('options',{}) or self.game['game_id'] in ['BalloonMania','ChickenShot','KickerMania','OpenIt','HotChilliBells','RoyalBeellionHoldAndWin','WildTiger2']:
   self.protocol_metadata.update(legacy_metadata.prove_native_variants(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if isinstance(initial.get('options',{}).get('bet'),int) and initial.get('flow',{}).get('available_actions')==['init','play']:
   self.protocol_metadata.update(legacy_metadata.prove_fixed_play(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if (fm and 'base_bet' not in fm) or initial.get('options',{}).get('valid_bets'):
   self.protocol_metadata.update(legacy_metadata.prove_default(self.game['game_id'],self.opener))
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  if self.protocol_metadata:
   envelope=NativeInit(initial);envelope.protocol_metadata=self.protocol_metadata;return envelope
  return initial
 def checkpoint(self,operation):
  cookies=[]
  for c in self.opener.handlers:
   if isinstance(c,urllib.request.HTTPCookieProcessor):
    cookies=[dict(name=x.name,value=x.value,domain=x.domain,path=x.path,secure=x.secure,expires=x.expires) for x in c.cookiejar]
  save(getattr(self,'private_session_path',PRIVATE/(self.game['game_id']+'.session.json')),dict(fresh_demo=True,game_id=self.game['game_id'],api=self.api,page=self.page,csrf_name=self.csrf_name,csrf_value=self.csrf_value,cookies=cookies,series=self.series,last_response=getattr(self,'last_response',None),last_request=getattr(self,'last_request',None),public_events=self.events,money_checks=self.money_checks,active_mode=getattr(self,'active_mode',None),operation=operation,updated_at=now()))
 def call(self,command,options=None):
  pause=max(0,.5-(time.monotonic()-getattr(self,'last_call_epoch',0)))
  if pause:time.sleep(pause)
  self.last_call_epoch=time.monotonic()
  q={'command':command,'extra_data':{'round_series_id':self.series}}
  if options is not None:q['options']=options
  self.last_request=q
  headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json','Accept':'application/json','Origin':'https://demo.bgaming-network.com','Referer':self.page,self.csrf_name:self.csrf_value}
  # Never retry a POST after timeout or transport failure: its result is uncertain.
  self.checkpoint(dict(command=command,status='sending'))
  try:
   with self.opener.open(urllib.request.Request(self.api,data=json.dumps(q).encode(),headers=headers),timeout=45) as r:
    raw=r.read();status=r.status
  except urllib.error.HTTPError as error:
   raw=error.read();status=error.code
   try:rejected=json.loads(raw)
   except ValueError:rejected={'body_format':'non_json','bytes':len(raw)}
   self.events.append(dict(time=now(),request=self.clean.clean(q),response=self.clean.clean(rejected),status=status,response_sha256=hashlib.sha256(raw).hexdigest()))
   self.checkpoint(dict(command=command,status='http_rejection',http_status=status))
   raise RuntimeError('HTTP rejection '+str(status)+'; no automatic retry') from None
  except Exception as error:
   self.events.append(dict(time=now(),request=self.clean.clean(q),status='uncertain',error_type=type(error).__name__))
   self.checkpoint(dict(command=command,status='uncertain'))
   raise RuntimeError('Uncertain POST; no retry') from None
  try:response=json.loads(raw)
  except ValueError:
   digest=hashlib.sha256(raw).hexdigest();name=self.game['game_id']+'.'+digest+'.unparsed-response.bin';PRIVATE.mkdir(parents=True,exist_ok=True);(PRIVATE/name).write_bytes(raw)
   self.events.append(dict(time=now(),request=self.clean.clean(q),response={'body_format':'non_json','bytes':len(raw)},status=status,response_sha256=digest));self.checkpoint(dict(command=command,status='received_unparsed',body_sha256=digest,private_body=name))
   raise RuntimeError('Non-JSON API response preserved privately; no retry') from None
  self.events.append(dict(time=now(),request=self.clean.clean(q),response=self.clean.clean(response),status=status,response_sha256=hashlib.sha256(raw).hexdigest()))
  self.last_response=response;self.checkpoint(dict(command=command,status='received'))
  return response
 def continuation_options(self,command):
  mode=getattr(self,'active_mode',{});options=mode.get('continuation_options')
  if command=='freespin' and mode.get('freespin_options'):return dict(options or {},**mode['freespin_options'])
  return options
 def settle(self,r):
  for _ in range(500):
   f=r.get('flow',{});state=f.get('state');available=[x for x in f.get('available_actions',[]) if x!='init']
   if state=='closed':return r
   if set(available)=={'freespin','buy_extra_bonus'} and not self.protocol_metadata.get('extra_bonus_command_verified'):
    from legacy_metadata import prove_default
    self.protocol_metadata.update(prove_default(self.game['game_id'],self.opener))
   if set(available)=={'freespin','buy_extra_bonus'} and getattr(self,'protocol_metadata',{}).get('extra_bonus_command_verified'):
    metadata=self.protocol_metadata;prices=r.get('features',{}).get('bonus_data',{}).get('bonus_game_prices',{});covered=getattr(self,'active_extra_types',set());operations=getattr(self,'bonus_operations',[]);before=r
    if not isinstance(prices,dict) or not set(prices)<=set(metadata['extra_bonus_types']) or any(value is not None and (type(value) is not int or value<0) for value in prices.values()):raise RuntimeError('Unknown optional bonus price schema; no input sent')
    eligible=[name for name in metadata['extra_bonus_types'] if isinstance(prices.get(name),int) and not isinstance(prices[name],bool) and prices[name]>0]
    self.offered_extra_types=getattr(self,'offered_extra_types',set())|set(eligible)
    priority=getattr(self,'active_mode',{}).get('extra_priority',metadata['extra_bonus_types'])
    if len(priority)!=len(set(priority)) or set(priority)!=set(metadata['extra_bonus_types']):raise RuntimeError('Invalid optional-bonus priority; no input sent')
    name=next((name for name in priority if name in eligible and name not in covered and prices[name]<=r['balance']['wallet']),None)
    if name:
     price=prices[name];index=len(self.events);r=self.call('buy_extra_bonus',{'bonus_type':name});actual=r.get('balance',{}).get('wallet');expected=before['balance']['wallet']-price;ok=actual==expected;self.money_checks.append(dict(kind='extra_bonus_native_debit',bonus_type=name,cost_native=price,expected=expected,actual=actual,ok=ok))
     if not ok:raise RuntimeError('Extra bonus native debit mismatch; no further input')
     if r.get('features',{}).get('bonus_data',{}).get('last_purchased_extra_bonus')!=name:raise RuntimeError('Extra bonus not confirmed by server')
     covered.add(name);self.active_extra_types=covered;operations.append(dict(bonus_type=name,cost_native=price,event=index,status='applied_to_open_bonus'));self.bonus_operations=operations;continue
    r=self.call('freespin',getattr(self,'active_mode',{}).get('continuation_options'))
    if r.get('balance',{}).get('wallet')!=before['balance']['wallet']:raise RuntimeError('Unexpected freespin wallet change after optional extras')
    continue
   if self.game['game_id']=='CatsSoup' and state=='play_bonus':
    from cats_choices import next_choice
    if not self.protocol_metadata.get('cats_bottle_count'):raise RuntimeError('Cats Soup choice source not verified')
    options=next_choice(r,self.protocol_metadata);before=r;index=len(self.events);r=self.call('play_bonus',options);self.choice_actions=getattr(self,'choice_actions',[])+[dict(event=index,command='play_bonus',options=options)]
   elif self.game['game_id']=='AliceWonderLuck' and state in ('gamble_bonus','pick_cards'):
    if not self.protocol_metadata.get('alice_choices_verified'):raise RuntimeError('Alice choice source not verified')
    from alice_choices import next_action
    progress=getattr(self,'alice_progress',{});q=next_action(r,getattr(self,'active_mode',{}),progress,self.protocol_metadata);before=r;index=len(self.events);r=self.call(q['command'],q['options']);self.alice_progress=progress;self.choice_actions=getattr(self,'choice_actions',[])+[dict(event=index,command=q['command'],options=q['options'])]
   elif available==['gamble_bonus'] and self.game['game_id']=='FrenzyClusters':
    portal=getattr(self,'active_mode',{}).get('selected_portal',0)
    if not isinstance(portal,int) or not 0<=portal<5:raise RuntimeError('Portal index outside verified client range')
    before=r;time.sleep(.5);r=self.call('gamble_bonus',{'selected_portal':portal})
   elif len(available)==1 and available[0] in ('preselection_game','play_preselection_game'):
    command=available[0]
    if command not in self.protocol_metadata.get('legacy_continuations',[]):
     from legacy_metadata import prove_continuations
     self.protocol_metadata.update(prove_continuations(self.game['game_id'],self.opener))
    if command not in self.protocol_metadata.get('legacy_continuations',[]):raise RuntimeError('Preselection request fields not proved; no input sent')
    before=r;r=self.call(command,self.protocol_metadata.get('continuation_options',{}).get(command))
   else:
    if len(available)!=1 or available[0] not in ('freespin','respin','play_bonus'):raise RuntimeError('Unrecognized continuation or choice; manual review required')
    if self.protocol_metadata.get('continuation_whitelist') and available[0] not in self.protocol_metadata['continuation_whitelist']:raise RuntimeError('Continuation outside this source-verified lifecycle; review required')
    before=r;time.sleep(.5);options=self.continuation_options(available[0]);r=self.call(available[0],options)
    if available[0]=='freespin' and options and options.get('freespins_type') and not getattr(self,'freespin_type_confirmed',False):
     if r.get('features',{}).get('freespins_type')!=options['freespins_type']:raise RuntimeError('Free-spin type not confirmed by native response; review required')
     self.freespin_type_confirmed=True;self.choice_actions=getattr(self,'choice_actions',[])+[dict(event=len(self.events)-1,command='freespin',options=options,kind='freespin_type_selection')]
   if r.get('balance',{}).get('wallet')!=before.get('balance',{}).get('wallet'):raise RuntimeError('Unexpected continuation wallet change; review required')
  raise RuntimeError('Continuation safety limit; unresolved round')
 def run_mode(self,mode,init):
  if mode.get('protocol')=='blackjack-extra':
   from blackjack_extra import run
   return run(self,mode,init)
  if mode.get('protocol')=='native-modes-extra':
   from native_modes_extra import run
   return run(self,mode,init)
  if mode.get('protocol') in ['native-rocket-dice','native-mine-ladder']:
   from native_tables_extra import run
   return run(self,mode,init)
  if mode.get('protocol')=='royal-roulette':
   from royal_roulette import run
   return run(self,mode,init)
  if mode.get('protocol')=='classic-roulette':
   from classic_roulette import run
   return run(self,mode,init)
  if mode.get('protocol')=='native-play-modes':
   from native_play_modes import run
   return run(self,mode,init)
  if mode.get('protocol')=='legacy-limbo':
   from limbo import run
   return run(self,mode,init)
  if mode.get('protocol')=='classic-heads':
   from classic_heads import run
   return run(self,mode,init)
  if mode.get('protocol')=='legacy-plinko':
   from classic_plinko import run_mode
   return run_mode(self,mode,init)
  if mode.get('protocol')=='legacy-v1-slots':
   from old_slots import run_mode
   return run_mode(self,mode,init)
  if mode.get('protocol') in ('jsonrpc','jsonrpc-cocos','jsonrpc-product-round','jsonrpc-rpc-extra','jsonrpc-final-pair','jsonrpc-four-modern-slots'):return self.hyper.run_mode(mode,init)
  if mode.get('protocol')=='baccarat':return self.run_baccarat_mode(mode,init)
  if mode.get('protocol')=='sugar_plinko':return self.run_sugar_mode(mode,init)
  self.active_mode=mode
  self.freespin_type_confirmed=False
  self.active_extra_types=set();self.offered_extra_types=set();extra_start=len(getattr(self,'bonus_operations',[]))
  self.alice_progress={};choice_start=len(getattr(self,'choice_actions',[]))
  old=self.prev or init
  if mode['command'] not in old.get('flow',{}).get('available_actions',[]):raise RuntimeError('Action not allowed by current state')
  b=old.get('balance',{});credit=b.get('game',0) if old.get('flow',{}).get('state')=='closed' else 0
  if b.get('wallet',0)+credit<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
  start=len(self.events);r=self.call(mode['command'],mode['options']);expected=b['wallet']+credit-mode['cost_native'];actual=r.get('balance',{}).get('wallet');check=dict(expected=expected,actual=actual,ok=actual==expected)
  self.money_checks.append(check)
  if not check['ok']:raise RuntimeError('Wallet reconciliation mismatch; review required')
  requested=mode['options'].get('purchased_feature')
  if requested and r.get('flow',{}).get('purchased_feature',{}).get('name')!=requested:raise RuntimeError('Requested feature not confirmed by server; review required')
  if requested and 'purchased_feature_level' in mode['options']:
   expected_level=mode['options']['purchased_feature_level'];actual_level=r.get('flow',{}).get('purchased_feature',{}).get('level');ok=actual_level is not None and str(actual_level)==str(expected_level);self.money_checks.append(dict(kind='purchased_feature_level',expected=expected_level,actual=actual_level,ok=ok))
   if not ok:raise RuntimeError('Requested purchase tier not confirmed by native response; review required')
  r=self.settle(r);self.prev=r
  return dict(mode=mode,status='closed',first_event=start,last_event=len(self.events)-1,final_balance=r.get('balance'),final_state=r.get('flow',{}).get('state'),bonus_operations=[dict(x,bonus_round_closed=True) for x in getattr(self,'bonus_operations',[])[extra_start:]],extra_types_offered=sorted(self.offered_extra_types),extra_types_tested=sorted(self.active_extra_types),choice_actions=getattr(self,'choice_actions',[])[choice_start:],manual_card_indices=self.alice_progress.get('used_indices',[]))
 def run_sugar_mode(self,mode,init):
  old=self.prev or init
  if 'play' not in old.get('available_commands',[]) and old.get('game',{}).get('state')=='closed' and 'init' in old.get('available_commands',[]):
   before=old['balance'];old=self.call('init')
   if old.get('balance')!=before:raise RuntimeError('Plinko init balance changed unexpectedly')
  if 'play' not in old.get('available_commands',[]):raise RuntimeError('Plinko play not allowed')
  balance=old.get('balance')
  if not isinstance(balance,int):raise RuntimeError('Unverified Plinko balance type')
  if balance<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
  start=len(self.events);r=self.call('play',mode['options']);game=r.get('game',{})
  if game.get('state')!='closed':raise RuntimeError('Plinko unresolved state/choice; review required')
  outcome=game.get('outcome',[])
  if not outcome or not isinstance(outcome[-1],list) or not isinstance(outcome[-1][0],(int,float)):raise RuntimeError('Plinko outcome schema needs review')
  components=[x[0] for x in outcome]
  if not all(isinstance(x,(int,float)) for x in components):raise RuntimeError('Plinko child win schema needs review')
  win=sum(components);expected=balance-mode['cost_native']+win;actual=r.get('balance');check=dict(expected=expected,actual=actual,ok=expected==actual);self.money_checks.append(check)
  if not check['ok']:raise RuntimeError('Plinko monetary reconciliation mismatch; review required')
  self.prev=r
  return dict(mode=mode,status='closed',first_event=start,last_event=len(self.events)-1,final_balance=actual,final_state='closed',win_native=win,win_components_native=components,outcome_count=len(outcome))

 def run_baccarat_mode(self,mode,init):
  old=self.prev or init
  if mode['command'] not in old.get('available_commands',[]) and old.get('game',{}).get('state')=='closed' and 'init' in old.get('available_commands',[]):
   old_balance=old['balance'];old=self.call('init')
   if old.get('balance')!=old_balance:raise RuntimeError('Baccarat init balance changed unexpectedly')
   self.prev=old
  if mode['command'] not in old.get('available_commands',[]):raise RuntimeError('Baccarat command not currently allowed')
  balance=old.get('balance')
  if not isinstance(balance,int):raise RuntimeError('Unverified Baccarat balance type')
  if balance<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
  start=len(self.events);r=self.call(mode['command'],mode['options'])
  allowed=r.get('available_commands',[])
  if r.get('game',{}).get('state')!='closed':raise RuntimeError('Baccarat continuation/choice needs review')
  win=r.get('bets',{}).get('win_amount')
  if not isinstance(win,(int,float)):raise RuntimeError('Baccarat win_amount missing; inspect response')
  expected=balance-mode['cost_native']+win;actual=r.get('balance')
  check=dict(expected=expected,actual=actual,ok=expected==actual);self.money_checks.append(check)
  if not check['ok']:raise RuntimeError('Baccarat wallet mismatch; review required')
  self.prev=r
  return dict(mode=mode,status='closed',first_event=start,last_event=len(self.events)-1,final_balance=actual,final_state=r.get('game',{}).get('state'),win_native=win)

def modes_from_init(init,metadata=None):
 metadata=metadata or getattr(init,'protocol_metadata',{})
 if metadata.get('blackjack_extra_verified'):
  from blackjack_extra import plan
  return plan(init,metadata)
 if metadata.get('native_modes_extra_verified'):
  from native_modes_extra import plan
  return plan(init,metadata)
 if metadata.get('native_tables_verified'):
  from native_tables_extra import plan
  return plan(init,metadata)
 if metadata.get('scratch_packs_verified'):
  from scratch_packs import plan
  return plan(init,metadata)
 if metadata.get('royal_roulette_verified'):
  from royal_roulette import plan
  return plan(init,metadata)
 if metadata.get('classic_roulette_verified'):
  from classic_roulette import plan
  return plan(init,metadata)
 if metadata.get('native_play_selector'):
  from native_play_modes import plan
  return plan(init,metadata)
 if metadata.get('limbo_thresholds'):
  from limbo import plan
  return plan(init,metadata)
 if metadata.get('line_count_modes'):
  from line_count_modes import plan
  return plan(init,metadata)
 if metadata.get('paid_volatility_values'):
  from volatility_modes import plan
  return plan(init,metadata)
 if metadata.get('indexed_rows'):
  from indexed_rows import plan
  return plan(init,metadata)
 if metadata.get('classic_heads_verified'):
  from classic_heads import plan
  return plan(init,metadata)
 if metadata.get('gold_symbols_factors'):
  from gold_symbols import plan
  return plan(init,metadata)
 if metadata.get('classic_plinko_verified'):
  from classic_plinko import plan
  return plan(init,metadata)
 if metadata.get('protocol')=='legacy-v1-slots':
  from old_slots import plan
  return plan(init,metadata)
 if init.get('jsonrpc')=='2.0':
  from hyperhive_adapter import plan_modes
  return plan_modes(init,metadata or getattr(init,'protocol_metadata',None))
 o=init['options'];currency=o['currency']
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Unverified currency schema')
 if metadata.get('native_variants'):
  from native_variants import plan
  return plan(init,metadata)
 if metadata.get('fixed_play_verified'):
  bet=o['bet']
  if not isinstance(bet,int) or bet<=0 or 'play' not in init.get('flow',{}).get('available_actions',[]):raise ValueError('Invalid fixed play state')
  return [dict(name='normal',command='play',options={'bet':bet,'bonus':False},cost_native=bet)]
 if o.get('valid_bets') and metadata.get('rows_parameter_verified'):
  import copy
  result=[]
  for row,bets in o['valid_bets'].items():
   local=copy.deepcopy(init);opts=local['options'];opts.pop('valid_bets');opts['available_bets']=bets;fm=opts.get('feature_options',{}).get('feature_multipliers',{})
   for feature,value in list(fm.items()):
    if isinstance(value,dict):
     if not metadata.get('rows_feature_level_verified'):raise ValueError('Rows feature-level mapping needs review')
     if row in value:fm[feature]={row:value[row]}
     else:del fm[feature]
   for mode in modes_from_init(local,metadata):
    if mode['name']=='normal':
     from fractions import Fraction
     factor=metadata.get('rows_normal_factors',{}).get(row)
     if factor is None:raise ValueError('Normal rows price not proved by client')
     cost=mode['cost_native']*Fraction(factor)
     if cost.denominator!=1:raise ValueError('Fractional rows cost needs review')
     mode['cost_native']=int(cost)
    mode['name']+='@rows:'+row;mode['options']['rows']=row;mode['continuation_options']={'rows':row};result.append(mode)
  return result
 if 'line_bets' in o and 'freespin_buy_miltipliers' in o and 'game_modes' in o and 'multipliers' in o:
  from fractions import Fraction
  bet=min(o['line_bets']);result=[];prices=o['freespin_buy_miltipliers'];disabled=o.get('disabled_features',[])
  feature_names=['high_chance_buy','multiplier_buy','respin_buy']
  for risk in o['game_modes']:
   for rows_text in o['paytable'][risk]:
    rows=int(rows_text);positions=[]
    for row,values in o['multipliers'][risk][rows_text].items():
     available=[i for i,v in enumerate(values) if v>1]
     if available:positions.append([int(row),available[len(available)//2]])
    enabled=[f for f in feature_names if f not in disabled and f in prices and (f!='multiplier_buy' or positions)]
    for mask in range(1<<len(enabled)):
     purchase={};cost=Fraction(bet)
     for bit,f in enumerate(enabled):
      if mask&(1<<bit):purchase[f]=positions if f=='multiplier_buy' else True;cost+=bet*Fraction(str(prices[f]))
     if cost.denominator!=1:raise ValueError('Plinko fractional native cost needs review')
     options={'bet':bet,'bonus':False,'game_mode':risk,'rows':rows,'purchased_feature':purchase}
     result.append(dict(name=f'{risk}/rows:{rows}/'+('+'.join(purchase) or 'normal'),protocol='sugar_plinko',command='play',options=options,cost_native=int(cost)))
  return result
 if 'available_bets' not in o and 'bet_types' in o:
  allowed={'player','banker','tie','player_pair','banker_pair','any_pair','perfect_pair','player_bonus','banker_bonus'}
  types=o['bet_types'];minimum=o['min_bet']
  if not types or not set(types)<=allowed or not isinstance(minimum,int) or minimum<=0 or 'play' not in init.get('available_commands',[]):raise ValueError('Unverified Baccarat protocol')
  modes=[]
  for kind in types:
   bets=[{'type':kind,'amount':minimum}]
   if kind not in ('player','banker','tie'):bets.insert(0,{'type':'banker' if kind.startswith('banker') else 'player','amount':minimum})
   modes.append(dict(name='bet:'+kind,protocol='baccarat',command='play',options={'bets':bets},cost_native=sum(x['amount'] for x in bets)))
  if 'demo_play' in init.get('available_commands',[]):modes.append(dict(name='free_hand',protocol='baccarat',command='demo_play',options={'bets':[{'type':'player'}]},cost_native=0))
  return modes
 bets=o['available_bets'];bet=min(bets)
 if not isinstance(bet,int) or bet<=0:raise ValueError('Invalid minimum bet')
 modes=[dict(name='normal',command='spin',options={'bet':bet},cost_native=bet)]
 fo=o.get('feature_options',{});fm=fo.get('feature_multipliers',{});base=fm.get('base_bet');disabled=fo.get('disabled_features',[])
 if base is None and metadata.get('source_verified') is True:base=metadata.get('feature_default_base_bet')
 for feature,mult in fm.items():
  if feature=='base_bet' or feature in disabled:continue
  pairs=mult.items() if isinstance(mult,dict) else [(None,mult)]
  for level,value in pairs:
   if not isinstance(base,int) or base<=0 or not isinstance(value,int) or value<=0:raise ValueError('Unverified feature cost schema')
   numerator=bet*value;cost,remainder=divmod(numerator,base)
   if remainder:
    kind='antebet' if feature.endswith('_chance') else 'purchase'
    if metadata.get('price_rounding',{}).get(kind)!='ceil':raise ValueError('Unverified feature cost schema')
    cost+=1
   options={'bet':bet,'purchased_feature':feature}
   if level is not None:options['purchased_feature_level']=str(level)
   modes.append(dict(name=feature+(':'+str(level) if level is not None else ''),command='spin',options=options,cost_native=cost))
 if metadata.get('alice_choices_verified'):
  from alice_choices import expand
  return expand(modes,metadata)
 if metadata.get('freespin_types'):
  from freespin_types import expand
  return expand(modes,metadata)
 return modes
def completion_status(report,metadata):
 status='complete_declared_modes' if all(x['status'] in ('closed','not_applicable') for x in report['modes']) and not metadata.get('unresolved') else 'partial'
 if any(check.get('ok') is False and not check.get('superseded') for check in report.get('checks',[])):status='partial'
 if metadata.get('extra_bonus_command_verified'):
  tested={t for m in report['modes'] for t in m.get('extra_types_tested',[])};offered={t for m in report['modes'] for t in m.get('extra_types_offered',[])};pending=set(metadata['extra_bonus_types'])-tested
  report['bonus_mode_coverage']=dict(source_types=metadata['extra_bonus_types'],offered=sorted(offered),tested=sorted(tested),pending=[dict(bonus_type=t,reason='Source-known optional bonus purchase not exercised') for t in sorted(pending)])
  if pending:status='partial'
 return status

def record_queue_end(state,queue):
 remaining=sum(game['game_id'] not in state['results'] for game in queue);state['selected_queue_remaining']=remaining
 if remaining:state.pop('queue_pass_finished_at',None);state['queue_paused_at']=now()
 else:state['queue_pass_finished_at']=now();state.pop('queue_paused_at',None)
 return state

if __name__=='__main__':
 from checkpoint_guard import acquire,require_inactive
 runner_lock_handle=acquire(ROOT/'runner.lock')
 p=argparse.ArgumentParser();p.add_argument('--limit',type=int);p.add_argument('--game');a=p.parse_args()
 cat=json.loads((ROOT/'catalog-live.json').read_text(encoding='utf8'));queue=[x for x in cat['games'] if x['demo_url'] and x['game_id'] and x.get('game_type')=='Slots']
 if a.game:queue=[x for x in queue if x['game_id']==a.game]
 if a.limit:queue=queue[:a.limit]
 state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else dict(started_at=now(),last_launch_epoch=0,results={},policy={'minimum_seconds_between_game_launches':60,'currency':'FUN','server':'demo'})
 require_inactive(state)
 state.setdefault('policy',{}).update(game_types=['Slots'],scope_instruction='Only slots; exclude poker, blackjack and other indefinite/table/casual games per latest user instruction')
 for game in queue:
  gid=game['game_id']
  if gid in state['results']:continue # Never repeat an uncertain/partial game automatically.
  if (ROOT/'STOP').exists() and (ROOT/'STOP').read_text(encoding='utf8').strip()!='CONTINUE':break
  delay=max(0,60-(time.time()-state['last_launch_epoch']))
  if delay:time.sleep(delay)
  if (ROOT/'STOP').exists() and (ROOT/'STOP').read_text(encoding='utf8').strip()!='CONTINUE':break
  if not re.fullmatch('[A-Za-z0-9_-]+',gid):continue
  state.pop('queue_pass_finished_at',None);state['last_launch_epoch']=time.time();state['active_game']=gid;state['updated_at']=now();save(state_path,state)
  import importlib
  import run_demo_qa as runtime
  importlib.reload(runtime)
  report=dict(game=game,started_at=now(),status='starting',modes=[],events=[],checks=[]);demo=runtime.Demo(game);report_path=OUT/(gid+'.json');save(report_path,report)
  try:
   init=demo.launch();report['bootstrap']=demo.bootstrap;report['protocol']=getattr(demo,'protocol','legacy');report['protocol_metadata']=getattr(demo,'protocol_metadata',{});report['declared_modes']=runtime.modes_from_init(init);report['status']='running'
   for mode in report['declared_modes']:
    result=demo.run_mode(mode,init);report['modes'].append(result);report['events']=demo.events;report['checks']=demo.money_checks;save(report_path,report)
   report['status']=runtime.completion_status(report,getattr(demo,'protocol_metadata',{}))
  except Exception as error:
   report['status']='needs_review';report['error_type']=type(error).__name__;report['reason']=str(error) if isinstance(error,(RuntimeError,ValueError,KeyError)) else 'Launch/network failure; no automatic retry'
   if isinstance(error,urllib.error.HTTPError):report['http_failure']=dict(status=error.code,host=urlsplit(error.url).hostname,path=urlsplit(error.url).path,phase='bootstrap_or_static_resource',no_automatic_retry=True)
  retain_launch_evidence(report,demo);report['events']=demo.events;report['checks']=demo.money_checks;report['finished_at']=now();save(report_path,report)
  state['results'][gid]=dict(status=report['status'],modes_closed=sum(x['status']=='closed' for x in report['modes']),report='live/'+gid+'.json');state['active_game']=None;state['updated_at']=now();save(state_path,state)
  print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],flush=True)
 record_queue_end(state,queue);save(state_path,state)
