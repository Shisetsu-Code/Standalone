"""Pinned YommiRush/JokerVsJoker JSON-RPC req/lifecycle adapters. No network at import.

run() only uses an explicitly supplied existing Hyperhive.request transport. Native
FUN values are preserved; source model-win units are converted only where explicit
Joker Config.bet=10 display math proves the relationship. No replay/search/init.
"""
import copy
from decimal import Decimal
from fractions import Fraction
import hashlib

PINS={
 'YommiRush':'fde03472331ff66c19c1566000073e641f325cf1e47735eb8d7742bc9f5f2b83',
 'JokerVsJoker':'f1502a31115a48f4f347bf74ffcdd92798f69bb9e56df290b351d4dd2894ec5d',
}
FEATURES={
 'YommiRush':{'buy_chance':3,'buy_bonus':100,'buy_bonus_and_chance':250},
 'JokerVsJoker':{'buy_bonus':60,'buy_chance':10},
}
MODEL_FEATURES={'buy_chance':'MORE_PETS','buy_bonus':'BONUS','buy_bonus_and_chance':'SUPER_BONUS'}


def metadata(gid,source,allowed):
 digest=hashlib.sha256(source.encode('utf8')).hexdigest()
 if gid not in PINS or digest!=PINS[gid]:raise ValueError('Exact game-specific reviewed source required')
 if not isinstance(allowed,list) or any(type(x) is not str for x in allowed):raise ValueError('Received feature whitelist required')
 if gid=='YommiRush':
  needles=['actionV2:function(e,t){return _("play",e,t)}',
   'bet:g,integrationId:C,bet_type:R?"freebet":"bet",purchased_feature:j,modelRev:0,minExponent:y.default.state.ui.minExponent',
   'Object.values(Y).length&&(U.payload=Y)', '(0,d.parseToString)(n)', 'n[r]=t[r].toString()', 'c.default.action({state_lock:i.stateLock,req:U})',
   'a.FEATURES.MORE_PETS,"buy_chance"','a.FEATURES.BONUS,"buy_bonus"','a.FEATURES.SUPER_BONUS,"buy_bonus_and_chance"',
   's.BONUS,100n),s.SUPER_BONUS,250n),s.MORE_PETS,3n)', 't.betStep=20n', 't[a]=t[a]<1n?1n:t[a]',
   'q=i.balance-X.cost*BigInt(!$)', 'O.winnings=X.winnings', 'winnings:X.round.winnings,id:B.round,ended:X.outcome.roundEnd',
   'O.balance=i.playback.enabled?q:B.balance||0n', 'a("setStateLock",B.state_lock||null)']
 else:
  needles=['this.network.invoke("play",{token:this.network.token,req:{bet:i,bet_type:n,fe_exponent:this.globalState.feBetExponent,purchased_feature:e,balance:this.globalState.balance,buyBonusModeMultiplier:r}})',
   'let n=this.freeBets.isActive()&&!this.freeBets.isLastFreeBet()?"freebet":"default",r=1',
   '"buy_bonus"==e&&(r=this.globalState.buyBonusModeMultiplier)',
   'e=e||(this.globalState.businessmanMode?"buy_chance":null)',
   'this.busnesssmanModeMultiplier=10,this.buyBonusModeMultiplier=60',
   'bet:10,reels:3', 's.win/w.Config.bet', 's.totalWin/w.Config.bet',
   'const n=s.isNextFree', 's.isFreespin&&n', 'let s=t.stages[0]',
   'i=Math.max(i,this.calculate_exponent(t[s],e))',
   'let i=t/e.subunits,s=i.toString().includes(".")?i.toString().split(".")[1].length+1:0',
   'return Math.max(e.exponent,s)']
 evidence=[]
 for needle in needles:
  offset=source.find(needle)
  if offset<0:raise ValueError('Reviewed source contract missing: '+needle)
  evidence.append(dict(offset=offset,excerpt=needle))
 return dict(engine='final-rpc-pair',protocol='jsonrpc-final-pair',game_id=gid,
  source_verified=True,source_sha256=digest,features={k:v for k,v in FEATURES[gid].items() if k in allowed},
  global_only_aliases=[x for x in allowed if x not in FEATURES[gid]],evidence=evidence,
  request_family='facade-action' if gid=='YommiRush' else 'super-spin',
  omit_state_lock=gid=='JokerVsJoker', bet_wire_type='decimal-string' if gid=='YommiRush' else 'number',
  public_alias_fields=['result.round','result.step'] if gid=='YommiRush' else [],
  unresolved=[],limitations=['No received play fixture for either game in this source-only preparation.',
   'Fractional native payouts, changed currency, extra Joker stages or unknown response schema stop for review; no guessed rounding or retries.'])


def _proof(meta):
 gid=meta.get('game_id')
 if gid not in PINS or not meta.get('source_verified') or meta.get('source_sha256')!=PINS[gid]:raise ValueError('Pinned pair metadata required')
 if any(FEATURES[gid].get(k)!=v for k,v in meta.get('features',{}).items()):raise ValueError('Feature price differs from pinned source')
 return gid


def _integer(value):
 if type(value) is int and value>=0:return value
 if type(value) is str and value.isascii() and value.isdigit() and (value=='0' or not value.startswith('0')):return int(value)
 raise ValueError('Nonnegative native integer amount required; no float scaling')


def _boolean(value):
 if type(value) is bool:return value
 if type(value) is int and value in (0,1):return bool(value)
 raise ValueError('Source boolean/zero-one lifecycle field required')


def _initial(initial,meta):
 gid=_proof(meta);r=initial.get('result',initial);a=r.get('currency_attributes',{})
 if r.get('currency')!='FUN' or a.get('code')!='FUN' or a.get('subunits')!=100 or a.get('exponent')!=2:raise ValueError('Original captured native FUN currency contract required; never normalize another currency')
 if r.get('freebets'):raise ValueError('Funded/promotional freebets outside ordinary FUN plan')
 bets=r.get('config',{}).get('bet_limits',[])
 if not bets or any(type(b) is not int or b<=0 for b in bets):raise ValueError('Native bet whitelist invalid')
 if gid=='YommiRush' and (min(bets)!=20 or any(b%20 for b in bets)):raise ValueError('Yommi source bet-step/reward precision requires received native 20-step list')
 return r


def plan(initial,meta):
 r=_initial(initial,meta);bet=min(r['config']['bet_limits']);allowed=r['config'].get('purchased_features',[])
 modes=[dict(name='normal',protocol='jsonrpc-final-pair',feature=None,bet_native=bet,cost_native=bet)]
 modes.extend(dict(name=f,protocol='jsonrpc-final-pair',feature=f,bet_native=bet,cost_native=bet*multiplier)
              for f,multiplier in meta['features'].items() if f in allowed)
 return modes


def _precision(initial,gid):
 r=initial.get('result',initial)
 if gid=='YommiRush':return 2 # Source min reward=1 native at min betStep=20; 1/100 needs two places.
 exponent=r['currency_attributes']['exponent'];subunits=r['currency_attributes']['subunits']
 for bet in r['config']['bet_limits']:
  amount=Decimal(bet)/Decimal(subunits)
  if amount!=amount.to_integral_value():exponent=max(exponent,-amount.normalize().as_tuple().exponent+1)
 return exponent


def request(initial,mode,meta,last,*,first):
 gid=_proof(meta);_initial(initial,meta)
 feature=mode['feature']
 if feature is not None and feature not in meta['features']:raise ValueError('Unproved source feature alias')
 bet=mode['bet_native']
 if gid=='YommiRush':
  req=dict(bet=str(bet),bet_type='bet',modelRev=0,minExponent=_precision(initial,gid))
  if first and feature:req['purchased_feature']=feature
  # integrationId is undefined in the cached token-only frontend path and omitted.
  return req
 return dict(bet=bet,bet_type='default',fe_exponent=_precision(initial,gid),
  purchased_feature=feature if first or feature=='buy_chance' else None,
  balance=last['balance'],buyBonusModeMultiplier=60 if first and feature=='buy_bonus' else 1)


def _closed(result,gid):
 if 'resp' not in result:return result.get('state') is None
 if gid=='YommiRush':return _boolean(result.get('resp',{}).get('outcome',{}).get('roundEnd'))
 spin=result.get('resp',{}).get('super_spin',{});stages=spin.get('round',{}).get('stages',[])
 if len(stages)!=1:raise ValueError('Only source single-stage Joker response is proved')
 return not _boolean(stages[-1].get('isNextFree'))


def inspect(result,mode,meta,*,first,total_before):
 gid=_proof(meta);balance=_integer(result.get('balance'))
 if result.get('freebets'):raise ValueError('Unexpected funded freebet response')
 bet=mode['bet_native'];feature=mode['feature']
 if gid=='YommiRush':
  resp=result.get('resp',{})
  cost=_integer(resp.get('cost'));win=_integer(resp.get('winnings'))
  expected_cost=mode['cost_native'] if first else 0
  if cost!=expected_cost:raise ValueError('Yommi initial/source purchase cost or zero-cost continuation differs')
  if _integer(resp.get('bet'))!=bet or _integer(resp.get('payload',{}).get('bet'))!=bet:raise ValueError('Yommi native confirmed base bet differs')
  closed=_boolean(resp.get('outcome',{}).get('roundEnd'))
  cumulative=_integer(resp.get('round',{}).get('winnings'))
  if cumulative!=total_before+win:raise ValueError('Yommi cumulative round winnings mismatch')
  state=resp.get('state',{})
  if first and feature:
   echo=result.get('req',{}).get('purchased_feature')
   if echo!=feature and state.get('boughtFeature')!=MODEL_FEATURES[feature]:raise ValueError('Yommi purchased feature not confirmed by echo/source model state')
  if 'freeSpins' in state and (type(state['freeSpins']) is not int or state['freeSpins']<0 or (closed and state['freeSpins']!=0)):raise ValueError('Yommi free-spin state inconsistent with closure')
 else:
  spin=result.get('resp',{}).get('super_spin',{});stages=spin.get('round',{}).get('stages',[])
  if len(stages)!=1 or not isinstance(stages[0],dict):raise ValueError('Only source single-stage Joker response is proved')
  stage=stages[0];closed=not _boolean(stage.get('isNextFree'));is_free=_boolean(stage.get('isFreespin'))
  if not first and not is_free:raise ValueError('Joker continuation did not confirm free-spin stage')
  if first and feature=='buy_bonus' and not _boolean(stage.get('isBuyBonus')):raise ValueError('Joker buy_bonus not confirmed by source stage')
  value=Fraction(str(stage.get('win')))*bet/10
  if value<0 or value.denominator!=1:raise ValueError('Joker source model winnings require unproved native rounding')
  win=int(value);cost=mode['cost_native'] if first else 0
  cumulative=Fraction(str(stage.get('totalWin')))*bet/10
  if cumulative!=total_before+win:raise ValueError('Joker cumulative normalized round winnings mismatch')
  if 'finished' in spin and _boolean(spin['finished'])!=closed:raise ValueError('Joker finished/next-free lifecycle disagreement')
 if 'final' in result and _boolean(result['final'])!=closed:raise ValueError('Native final flag disagrees with source closure')
 return dict(balance_native=balance,cost_native=cost,win_native=win,cumulative_win_native=total_before+win,closed=closed)


def _validated_mode(initial,meta,mode):
 expected=next((m for m in plan(initial,meta) if m['feature']==mode.get('feature')),None)
 if expected is None or any(mode.get(k)!=expected[k] for k in ('protocol','feature','bet_native','cost_native')):raise ValueError('Mode differs from source whitelist/native price')
 return expected



def identifier_policy(result,previous=None):
 has_round='round' in result
 has_step='step' in result
 if has_round!=has_step:raise ValueError('Yommi partial round/step identifier presence is not accepted')
 policy='both_present' if has_round else 'both_absent'
 if has_round and (result['round'] in (None,'') or result['step'] in (None,'')):
  raise ValueError('Yommi present identifiers must contain native values')
 if previous is not None and previous!=policy:raise ValueError('Yommi mixed identifier policy in owned session')
 return policy


def _rpc_correlation(event):
 q=event.get('request',{});outer=event.get('response',{});result=outer.get('result',{})
 rid=q.get('id')
 if event.get('status')!=200 or type(rid) not in (str,int) or rid in ('',None) or outer.get('id')!=rid or q.get('method')!='play':
  raise ValueError('Yommi absent identifiers require matching owned RPC request/response IDs')
 if not isinstance(q.get('params',{}).get('state_lock'),str) or not q['params']['state_lock'] or not isinstance(result.get('state_lock'),str) or not result['state_lock']:
  raise ValueError('Yommi absent identifiers require explicit sequential source state_lock transport')
 return rid

def run(hyper,mode):
 meta=hyper.metadata;gid=_proof(meta);initial=hyper.initial
 if hyper.parent.game.get('game_id')!=gid:raise ValueError('Transport game differs from pinned source')
 _validated_mode(initial,meta,mode)
 if not _closed(hyper.last,gid):raise ValueError('Open native RPC round; no new paid trigger')
 before=_integer(hyper.last.get('balance'));start=len(hyper.parent.events)
 if before<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance',network_calls=0)
 total=0;first=True;steps=[];round_id=None;action_ids=set();policy=meta.get('received_identifier_policy')
 for _ in range(512):
  req=request(initial,mode,meta,hyper.last,first=first)
  response=hyper.request('play',req)['result']
  try:checked=inspect(response,mode,meta,first=first,total_before=total)
  except ValueError as error:
   hyper.parent.money_checks.append(dict(kind='final_rpc_pair_received_contract',event=len(hyper.parent.events)-1,ok=False,reason=str(error)))
   raise
  low=before-mode['cost_native'];high=low+checked['cumulative_win_native']
  if not low<=checked['balance_native']<=high:
   hyper.parent.money_checks.append(dict(kind='final_rpc_pair_native_interim_bounds',event=len(hyper.parent.events)-1,expected_bounds_native=[low,high],actual_native=checked['balance_native'],ok=False))
   raise ValueError('Native interim wallet contains unaccounted debit/credit; no next continuation')
  if gid=='YommiRush':
   policy=identifier_policy(response,policy)
   if policy=='both_absent':
    native_events=getattr(hyper,'raw_events',None) or hyper.parent.events
    _rpc_correlation(native_events[-1])
   else:
    if round_id is None:round_id=response['round']
    if response['round']!=round_id or response['step'] in action_ids:raise ValueError('Yommi changed parent round or repeated action identifier')
    action_ids.add(response['step'])
  total=checked['cumulative_win_native'];steps.append(dict(event=len(hyper.parent.events)-1,**checked))
  if checked['closed']:break
  first=False
 else:raise ValueError('Source RPC lifecycle bound reached; unresolved native round retained')
 expected=before-mode['cost_native']+total;actual=checked['balance_native']
 check=dict(kind='final_rpc_pair_native_round',game_id=gid,expected_native=expected,actual_native=actual,
            cost_native=mode['cost_native'],win_native=total,ok=expected==actual)
 hyper.parent.money_checks.append(check)
 if not check['ok']:raise ValueError('Native RPC pair balance mismatch; no balance edits/retries')
 if gid=='YommiRush':meta['received_identifier_policy']=policy
 return dict(mode=mode,status='closed',first_event=start,last_event=len(hyper.parent.events)-1,
             final_balance=actual,final_state='source_final',win_native=total,network_calls=len(steps),
             lifecycle_steps=steps,source_family=meta['request_family'],identifier_policy=policy if gid=='YommiRush' else None,
             identifier_limitation='Server round/step absent; owned sequential correlated RPC + source state_lock and source final/cumulative native constraints only' if policy=='both_absent' else None)


def audit(initial,events,meta):
 """Independent event replay; no copied runtime checks and no provider writes."""
 gid=_proof(meta);_initial(initial,meta);checks=[];rounds=[];last=initial['result'];active=None;policy=meta.get('received_identifier_policy');rpc_ids=set()
 for index,event in enumerate(events):
  method=event.get('request',{}).get('method')
  if method=='init':
   if active is not None:raise ValueError('RPC init cannot supersede an unresolved round')
   result=event.get('response',{}).get('result')
   _initial(result,meta)
   if index and _integer(result['balance'])!=_integer(last['balance']):checks.append(dict(event=index,kind='final_rpc_pair_explicit_init_observation',expected_native=_integer(last['balance']),actual_native=_integer(result['balance']),ok=False,note='Explicit non-wagering baseline observation; never a payout or superseding correction'))
   last=result;continue
  if event.get('status')!=200 or method!='play':raise ValueError('Rejected/uncertain or unknown RPC action retained')
  req=event['request'].get('params',{}).get('req')
  if not isinstance(req,dict):raise ValueError('Native pair request missing')
  if active is None:
   if not _closed(last,gid):raise ValueError('Pair audit trigger before source closure')
   feature=req.get('purchased_feature')
   mode=next((m for m in plan(initial,meta) if m['feature']==feature),None)
   if mode is None:raise ValueError('Pair audit feature outside source whitelist')
   active=dict(mode=mode,before=_integer(last['balance']),total=0,first_event=index,steps=0,round_id=None,action_ids=set())
  first=active['steps']==0;mode=active['mode']
  if req!=request(initial,mode,meta,last,first=first):raise ValueError('Pair audit request differs from exact source envelope')
  result=event['response']['result'];checked=inspect(result,mode,meta,first=first,total_before=active['total'])
  if gid=='YommiRush':
   policy=identifier_policy(result,policy)
   if policy=='both_absent':
    rpc_id=_rpc_correlation(event)
    if rpc_id in rpc_ids:raise ValueError('Repeated owned RPC identity in Yommi audit')
    rpc_ids.add(rpc_id)
   else:
    rid,aid=result['round'],result['step']
    if any(isinstance(v,str) and v.startswith('[REDACTED') for v in (rid,aid)):raise ValueError('Yommi public round/step aliases required before independent audit')
    if active['round_id'] is None:active['round_id']=rid
    if rid!=active['round_id'] or aid in active['action_ids']:raise ValueError('Yommi audit parent/action identity mismatch')
    active['action_ids'].add(aid)
  low=active['before']-mode['cost_native'];high=low+checked['cumulative_win_native']
  if not low<=checked['balance_native']<=high:checks.append(dict(event=index,kind='final_rpc_pair_native_interim_bounds',expected_bounds_native=[low,high],actual_native=checked['balance_native'],ok=False))
  active['total']=checked['cumulative_win_native'];active['steps']+=1;last=result
  if checked['closed']:
   expected=active['before']-mode['cost_native']+active['total'];actual=checked['balance_native'];check=dict(event=index,kind='final_rpc_pair_native_round',cost_native=mode['cost_native'],win_native=active['total'],expected_native=expected,actual_native=actual,ok=expected==actual);checks.append(check)
   rounds.append(dict(first_event=active['first_event'],last_event=index,feature=mode['feature'],source_final=True,network_calls=active['steps'],identifier_policy=policy if gid=='YommiRush' else None,identifier_limitation='Owned sequential correlated RPC/state_lock only; server round/step absent' if policy=='both_absent' else None,**check));active=None
 if active is not None:checks.append(dict(kind='final_rpc_pair_open_round',ok=False,reason='Source bonus lifecycle remains open'))
 return checks,rounds


def audit_report(report):
 events=report.get('events',[]);checks,rounds=audit(events[0]['response'],events,report['protocol_metadata'])
 return dict(game_id=report['game']['game_id'],status=report['status'],events=len(events),checks=checks,rounds=rounds,
             passed=sum(c['ok'] for c in checks),failed=sum(not c['ok'] for c in checks),modes_closed=sum(m['status']=='closed' for m in report.get('modes',[])))
