"""Static-source-gated native FUN blackjack protocols, with original money audit.

The transport, fresh-session provenance and pacing belong to the parent runner.
No imports, metadata extraction or mode planning perform any network operation.
"""
import hashlib
import re

CLASSIC=('BlackjackPro','MultihandBlackjack')
MODERN=('ClassicMultihandBlackjack','MultihandBlackjackPro2','SurrenderMultihandBlackjack')
SUPPORTED=CLASSIC+MODERN


def metadata(source,gid):
 if gid not in SUPPORTED:raise ValueError('Unproved blackjack game')
 if gid in CLASSIC:
  patterns=[r'My.games.'+gid+r'=\{',r'My.games.MultihandBlackjack=\{',
   r'setBetsMinMax\(\["1","3","5"\]',r'command:"deal",options:',
   r'command:"hit"\}',r'command:"stand"\}',r'command:"double"\}',
   r'command:"split",options:\{hand_id:""\+\(\w+\+1\)\}',
   r'command:"finish"',r'\.result.total',r'\.bets.total',
   r'"MultihandBlackjackPro"===\w+\?.{0,400}?\.chip=']
  hands=['1','3','5'];family='classic-deal'
 else:
  patterns=[r'playCommand=\w+.START',r'additionalPlayData=\{areas:',
   r'options:\{\.\.\.\w+.A.data.additionalPlayData\}',
   r'\{name:\w+,main:\{bet:',r'perfect_pair:\{bet:',r'twenty_one:\{bet:',
   r'standAction\(\{area_name:',r'hitAction\(\{area_name:',r'doubleAction\(\{area_name:',r'splitAction\(\{area_name:',
   r'insuranceAction\(\{areas:\[\]\}\)',r'insuranceAction\(\{areas:\w+\}\)',
   r'priceMultiplier=\{default:1,features:\{topt:1,pp:1,insurance:.5\}\}',
   r'UNKNOWN_HAND:"none"',r'SPLIT:"splited"',r'="splited_"',
   r'totalWin:0',r'status!==\w+.SPLIT',r'\.main\).*?win_amount',
   r'\.name.replace\(\w+,""\);\w+\[\w+\]\|\|!\w+.perfect_pair&&!\w+.twenty_one\|\|\(\w+\[\w+\]=\w+\)',
   r'finishAction\(\)\{.{0,220}?request\(\{command:\w+.FINISH\}']
  if gid=='SurrenderMultihandBlackjack':patterns += [r'surrenderAction\(\{area_name:',
   r'get isSurrendered\(\)\{.{0,200}?surrended.{0,130}?status',
   r'get displayWinAmount\(\)\{.{0,220}?this.isSurrendered\?.{0,200}?\.bet\)\|\|0\)/2:',
   r'\.surrended\|\|\(\w+-=\w+.main.win_amount\|\|0\)']
  hands=sorted(set(re.findall(r'c:"PrefabReference",p:\{name:"(area_\d+)"[^}]+prefabName:"bet-hand"',source)))
  if hands!=['area_'+str(i) for i in range(1,(5 if gid=='MultihandBlackjackPro2' else 3)+1)]:raise ValueError('Unproved registered native blackjack hand layout')
  family='native-areas'
 proofs=[]
 for pattern in patterns:
  m=re.search(pattern,source)
  if not m:raise ValueError('Unproved blackjack source: '+pattern)
  proofs.append(dict(pattern=pattern,offset=m.start(),excerpt=m.group()))
 return dict(blackjack_extra_verified=True,game_id=gid,protocol='blackjack-extra',family=family,hand_ids=hands,
             source_sha256=hashlib.sha256(source.encode()).hexdigest(),proofs=proofs,
             verification_limit='Static wire and source ledger contracts, synthetic tests only. Actual native insurance payout representation and receipt timing must pass strict parent-controlled live checks; no balancing fallback exists.')


def integer(value,name):
 if type(value) is not int or value<0:raise ValueError('Unproved native blackjack amount '+name)
 return value


def available(response,command):
 commands=response.get('available_commands',[])
 return bool(commands.get(command)) if isinstance(commands,dict) else command in commands


def terminal(gid,response):
 start='deal' if gid in CLASSIC else 'start'
 return (response.get('game',{}).get('state') in ('idle','closed','finished') and available(response,start)
         and not any(available(response,c) for c in ('finish','insurance','hit','stand','double','split','surrender')))


def plan(initial,meta):
 gid=meta.get('game_id');o=initial['options'];c=o['currency']
 if not meta.get('blackjack_extra_verified') or gid not in SUPPORTED or c.get('code')!='FUN' or c.get('subunits')!=100 or not terminal(gid,initial):raise ValueError('Unproved fresh native FUN blackjack initial state')
 integer(initial.get('balance'),'balance');bet=o['min_bet'] if gid in CLASSIC else o['bet_limits']['min_bet'];integer(bet,'min bet')
 if not bet:raise ValueError('Zero blackjack minimum')
 command='deal' if gid in CLASSIC else 'start';modes=[]
 def add(name,hands,target='normal',feature=None):
  if gid=='BlackjackPro':args={h:dict(chip=bet,**({'bonus':bet} if feature else {})) for h in hands}
  elif gid=='MultihandBlackjack':args=dict.fromkeys(hands,bet)
  else:
   args={'areas':[]}
   for hand in hands:
    area={'name':hand,'main':{'bet':bet}}
    for side in (('perfect_pair','twenty_one') if feature=='both_sides' else (feature,) if feature else ()):
     area[side]={'bet':bet}
    args['areas'].append(area)
  cost=len(hands)*bet*(2 if feature=='bonus' else 3 if feature=='both_sides' else 2 if feature else 1)
  modes.append(dict(name=name,protocol='blackjack-extra',game_id=gid,command=command,options=args,cost_native=cost,
                    target=target,source_sha256=meta['source_sha256']))
 targets=['normal','stand','hit','double','split']
 if gid in MODERN:targets+=['insurance_accept','insurance_skip']
 if gid=='SurrenderMultihandBlackjack':targets+=['surrender']
 for hand in meta['hand_ids']:
  for target in targets:add(hand+'/'+target,[hand],target)
  if gid=='BlackjackPro':add(hand+'/bonus',[hand],feature='bonus')
  if gid in MODERN and o['bet_limits'].get('max_side_bet',0)>=bet:
   for feature in ('perfect_pair','twenty_one','both_sides'):add(hand+'/'+feature,[hand],feature=feature)
 for count in range(2,len(meta['hand_ids'])):add('hand_count:'+str(count)+'/normal',meta['hand_ids'][:count])
 add('all_hands/normal',meta['hand_ids'])
 if gid=='BlackjackPro':add('all_hands/bonus',meta['hand_ids'],feature='bonus')
 return modes


def area_totals(areas,surrender_native=False):
 """Official source total: skip split parent main; deduplicate side bets by root."""
 if not isinstance(areas,list):raise ValueError('Missing native player areas')
 stake=0;wins=0;side_by_root={};names=set()
 for area in areas:
  name=area.get('name')
  if not isinstance(name,str) or not re.fullmatch(r'(?:splited_[12]_)?area_[1-5]',name) or name in names:raise ValueError('Unproved native player area identity')
  names.add(name);main=area.get('main',{})
  bet=integer(main.get('bet'),'area main bet');win=0 if main.get('win_amount') is None else integer(main['win_amount'],'area main win')
  if surrender_native and (area.get('surrended') is True or area.get('status')=='surrended'):
   if bet%2:raise ValueError('Fractional native surrender refund')
   win=bet//2 # Official displayWinAmount overrides hypothetical main.win_amount.
  if area.get('status')!='splited':stake+=bet;wins+=win
  root=re.sub(r'^splited_\d+_','',name)
  sides={key:area[key] for key in ('perfect_pair','twenty_one') if key in area}
  if sides and root not in side_by_root:
   # Official total helper keeps the first area carrying side fields per root,
   # including when split child placeholders repeat zeroed side results later.
   prior=side_by_root.setdefault(root,{})
   for key,item in sides.items():
    parsed=(integer(item.get('bet'),'side bet'),0 if item.get('win_amount') is None else integer(item['win_amount'],'side win'))
    prior[key]=parsed
 for sides in side_by_root.values():
  for bet,win in sides.values():stake+=bet;wins+=win
 return dict(stake_native=stake,win_native=wins)


def _hands(gid):return ['1','3','5'] if gid in CLASSIC else ['area_'+str(i) for i in range(1,(5 if gid=='MultihandBlackjackPro2' else 3)+1)]


def _active_bet(gid,response):
 if gid in CLASSIC:
  current=str(response.get('game',{}).get('current_hand',''))
  if current not in ('1','2','3','4','5','6'):raise ValueError('No current player hand')
  hand=response.get('bets',{}).get(current)
  if not isinstance(hand,dict):raise ValueError('Native classic current hand wager missing')
  return current,integer(hand.get('chip'),'classic current chip')
 current=response.get('current_area')
 matches=[a for a in response.get('areas',[]) if a.get('name')==current and a.get('status')!='splited']
 if current in ('none','dealer',None) or len(matches)!=1:raise ValueError('No unambiguous native active player area')
 return current,integer(matches[0].get('main',{}).get('bet'),'current area wager')


def request_cost(gid,request,initial,previous):
 """Independent raw wire-price derivation, including additional action debits."""
 if gid not in SUPPORTED:raise ValueError('Unsupported blackjack source family')
 command=request.get('command');args=request.get('options');o=initial['options'];start='deal' if gid in CLASSIC else 'start'
 if not available(previous,command):raise ValueError('Blackjack command not natively advertised')
 if command==start:
  if not terminal(gid,previous) or not isinstance(args,dict) or not args:raise ValueError('Blackjack new wager requires ready native round')
  total=0
  if gid in CLASSIC:
   if not set(args)<=set(_hands(gid)):raise ValueError('Unproved classic hand selection')
   for item in args.values():
    if gid=='BlackjackPro':
     if not isinstance(item,dict) or set(item) not in ({'chip'},{'chip','bonus'}):raise ValueError('Classic Pro requires native chip/bonus fields')
     bet=integer(item['chip'],'main chip');side=integer(item.get('bonus',0),'bonus chip')
     if side and not o['min_bet']<=side<=bet:raise ValueError('Classic bonus outside source main-dependent limits')
    else:bet=integer(item,'main chip');side=0
    if not o['min_bet']<=bet<=o['max_bet']:raise ValueError('Classic main wager outside original limits')
    total+=bet+side
  else:
   if set(args)!={'areas'} or not isinstance(args['areas'],list) or not args['areas']:raise ValueError('Native start requires area array only')
   names=set();limits=o['bet_limits']
   for area in args['areas']:
    if not isinstance(area,dict) or not {'name','main'}<=set(area) or not set(area)<={'name','main','perfect_pair','twenty_one'}:raise ValueError('Unproved native area wager fields')
    name=area['name']
    if name not in _hands(gid) or name in names:raise ValueError('Unproved native initial hand identity')
    names.add(name)
    for key in ('main','perfect_pair','twenty_one'):
     if key not in area:continue
     item=area[key]
     if not isinstance(item,dict) or set(item)!={'bet'}:raise ValueError('Native area wager must contain original bet only')
     amount=integer(item['bet'],'area wager');limit=limits.get('max_main_bet') if key=='main' else limits.get('max_side_bet',0)
     if not limits['min_bet']<=amount<=limit:raise ValueError('Native area wager outside original limits')
     total+=amount
  return total
 if command=='finish':
  if args is not None:raise ValueError('Blackjack finish has no options')
  return 0
 if command=='insurance' and gid in MODERN:
  if not isinstance(args,dict) or set(args)!={'areas'} or not isinstance(args['areas'],list) or len(set(args['areas']))!=len(args['areas']):raise ValueError('Unproved native insurance selection')
  cost=0;areas={a['name']:a for a in previous.get('areas',[]) if a.get('status')!='splited'}
  for name in args['areas']:
   if name not in areas or areas[name].get('insured'):raise ValueError('Insurance target is not an uninsured player area')
   bet=integer(areas[name].get('main',{}).get('bet'),'insured original main')
   if bet%2:raise ValueError('Fractional native insurance half stake')
   cost+=bet//2
  return cost
 if command not in ('hit','stand','double','split','surrender') or (command=='surrender' and gid!='SurrenderMultihandBlackjack'):raise ValueError('Unproved native hand action')
 current,bet=_active_bet(gid,previous)
 if gid in CLASSIC:
  if command=='split':
   if args!={'hand_id':str(int(current)+1)} or int(current)%2!=1:raise ValueError('Classic split requires next adjacent source hand ID')
  elif args is not None:raise ValueError('Classic hand action is optionless')
 elif args!={'area_name':current}:raise ValueError('Hand action must name exact native current player area')
 return bet if command in ('double','split') else 0


def new_ledger():return dict(stake_native=0,win_native=0,insurance_native=0,raw_engine_win_native=0,native_surrender_refund=0)


def reconcile(gid,previous,response,request,initial,ledger):
 """Strict original integer wallet equation; no raw balance edits or fallbacks."""
 if response.get('errors'):raise ValueError('Native blackjack server error; response retained')
 cost=request_cost(gid,request,initial,previous);before=integer(previous.get('balance'),'before wallet');actual=integer(response.get('balance'),'response wallet');command=request['command']
 if gid in CLASSIC:
  win=0 if command=='finish' or response.get('result') is None else integer(response['result'].get('total'),'classic scalar total prize')
  total=ledger['stake_native']+cost
  if command!='finish' and integer(response.get('bets',{}).get('total'),'classic total stake')!=total:raise ValueError('Classic cumulative native wager receipt mismatch')
  after=dict(stake_native=total,win_native=ledger['win_native']+win,insurance_native=0,raw_engine_win_native=ledger['win_native']+win,native_surrender_refund=0)
 else:
  totals=area_totals(response['areas'],surrender_native=gid=='SurrenderMultihandBlackjack') if 'areas' in response else dict(stake_native=ledger['stake_native'],win_native=ledger['win_native']) if command=='finish' else None
  if totals is None:raise ValueError('Native blackjack response lacks original areas')
  expected_stake=ledger['stake_native']+(0 if command=='insurance' else cost)
  if totals['stake_native']!=expected_stake:raise ValueError('Native area cumulative wager receipt mismatch')
  win=totals['win_native']-ledger['win_native']
  if win<0:raise ValueError('Native cumulative area award decreased; cannot guess payout semantics')
  engine=area_totals(response['areas'])['win_native'] if 'areas' in response else ledger.get('raw_engine_win_native',ledger['win_native'])
  refunded=sum(integer(a.get('main',{}).get('bet'),'surrender original stake')//2 for a in response['areas'] if a.get('surrended') is True or a.get('status')=='surrended') if gid=='SurrenderMultihandBlackjack' and 'areas' in response else ledger.get('native_surrender_refund',0)
  after=dict(totals,insurance_native=ledger['insurance_native']+(cost if command=='insurance' else 0),
             raw_engine_win_native=engine,native_surrender_refund=refunded)
 expected=before-cost+win
 if actual!=expected:raise ValueError(f'Blackjack native wallet mismatch: expected {expected}, actual {actual}')
 ledger.update(after)
 return dict(kind='blackjack_native_wallet',expected=expected,actual=actual,cost_native=cost,win_native=win,
             cumulative_stake_native=after['stake_native'],cumulative_win_native=after['win_native'],
             insurance_stake_native=after['insurance_native'],raw_engine_win_native=after['raw_engine_win_native'],
             native_surrender_refund=after['native_surrender_refund'],ok=True)


def _action_request(gid,command,current):
 if command=='finish':return {'command':'finish'}
 hand,_=_active_bet(gid,current)
 if gid in CLASSIC:return {'command':command,**({'options':{'hand_id':str(int(hand)+1)}} if command=='split' else {})}
 return {'command':command,'options':{'area_name':hand}}


def run(demo,mode,initial):
 gid=mode.get('game_id');current=demo.prev or initial
 if mode.get('protocol')!='blackjack-extra' or gid not in SUPPORTED or not terminal(gid,current):raise ValueError('Unproved or unresolved native blackjack round')
 first={'command':mode['command'],'options':mode['options']};cost=request_cost(gid,first,initial,current)
 if cost!=mode['cost_native']:raise ValueError('Declared blackjack cost differs from independent source wire price')
 if current['balance']<cost:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);ledger=new_ledger();target=mode['target'];reached=target=='normal'
 def send(request):
  nonlocal current
  before=current
  # Validate action/price before transport, then retain exact receipt before check.
  request_cost(gid,request,initial,before)
  response=demo.call(request['command'],request['options']) if 'options' in request else demo.call(request['command'])
  demo.prev=response;current=response
  demo.money_checks.append(reconcile(gid,before,response,request,initial,ledger))
 send(first)
 for _ in range(64):
  if terminal(gid,current):break
  if available(current,'finish'):send({'command':'finish'});continue
  if gid in MODERN and available(current,'insurance'):
   selected=[]
   if target=='insurance_accept' and not reached:
    selected=[a['name'] for a in mode['options']['areas']]
   request={'command':'insurance','options':{'areas':selected}}
   optional=request_cost(gid,request,initial,current)
   if optional>current['balance']:request['options']['areas']=[];selected=[]
   send(request)
   if target=='insurance_skip' or target=='insurance_accept' and selected:reached=True
   continue
  command=target if not reached and target in ('stand','hit','double','split','surrender') and available(current,target) else 'stand' if available(current,'stand') else 'hit' if available(current,'hit') else None
  if command is None:raise ValueError('No source-proved active player continuation')
  request=_action_request(gid,command,current);optional=request_cost(gid,request,initial,current)
  if optional>current['balance']:
   if not available(current,'stand'):raise ValueError('Insufficient native funds for active hand action')
   command='stand';request=_action_request(gid,command,current)
  send(request)
  if command==target:reached=True
 else:raise ValueError('Blackjack continuation bound exhausted; exact pending response retained')
 if not terminal(gid,current):raise ValueError('Blackjack terminal native command/state not proved')
 return dict(mode=mode,status='closed' if reached else 'needs_trigger',first_event=start,last_event=len(demo.events)-1,
             final_balance=current['balance'],final_state=current['game']['state'])


def resume_received(demo,mode,initial):
 """Normalize exact received surrendered refund offline; send advertised finish once."""
 gid=mode.get('game_id');events=demo.events;current=getattr(demo,'last_response',None) or demo.prev
 if gid!='SurrenderMultihandBlackjack' or mode.get('protocol')!='blackjack-extra' or mode.get('target')!='surrender' or len(events)<2:
  raise ValueError('Received blackjack recovery is restricted to surrendered native hand')
 currency=initial.get('options',{}).get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Received blackjack recovery requires original native FUN init')
 latest=events[-1]
 if latest.get('status')!=200 or latest.get('request',{}).get('command')!='surrender' or latest.get('response')!=current or current.get('game',{}).get('action')!='surrender' or current.get('game',{}).get('state')!='finished' or current.get('current_area')!='none' or not available(current,'finish') or available(current,'start'):
  raise ValueError('Not exact accepted surrendered response awaiting finish')
 if not any(a.get('surrended') is True or a.get('status')=='surrended' for a in current.get('areas',[])):raise ValueError('Received result lacks source surrender flag/status')
 starts=[i for i,e in enumerate(events[:-1]) if e.get('request',{}).get('command')=='start']
 if not starts:raise ValueError('Received surrender lacks original start')
 start=starts[-1]
 if events[start]['request'].get('options')!=mode['options']:raise ValueError('Received surrender start differs from supplied mode')
 ledger=new_ledger();before=events[start-1]['response'];checked=None
 for event in events[start:]:
  if event.get('status')!=200:raise ValueError('Received current blackjack round includes rejection')
  checked=reconcile(gid,before,event['response'],event['request'],initial,ledger);before=event['response']
 checked.update(normalized_received_surrender=True,normalized_received_surrender_event=len(events)-1)
 if not any(c.get('normalized_received_surrender_event')==len(events)-1 for c in demo.money_checks):demo.money_checks.append(checked)
 demo.prev=current;demo.active_mode=mode;response=demo.call('finish');demo.prev=response
 demo.money_checks.append(reconcile(gid,current,response,{'command':'finish'},initial,ledger))
 if not terminal(gid,response):raise ValueError('Received surrendered round did not close natively')
 return dict(mode=mode,status='closed',first_event=start,last_event=len(demo.events)-1,final_balance=response['balance'],
             final_state=response['game']['state'],normalized_existing_received_surrender=True)


def audit(report):
 """Replay source-derived request prices and raw receipts, ignoring runner checks."""
 gid=report.get('game',{}).get('game_id');events=report.get('events',[])
 if gid not in SUPPORTED or not events or events[0].get('request',{}).get('command')!='init' or events[0].get('status')!=200:raise ValueError('Blackjack audit requires original accepted init')
 initial=events[0]['response'];currency=initial.get('options',{}).get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Blackjack audit requires original native FUN units')
 integer(initial.get('balance'),'initial wallet');previous=initial;ledger=new_ledger();checks=[];paid_attempts=0;rounds=0;total=0;round_open=False;verified=set();paid={}
 for index,event in enumerate(events[1:],1):
  request=event.get('request',{});response=event.get('response',{});command=request.get('command')
  try:
   if event.get('status')!=200:raise ValueError('Rejected blackjack request is not covered gameplay')
   if command=='init':
    if not terminal(gid,previous) or response.get('balance')!=previous.get('balance'):raise ValueError('Unproved blackjack init reset or wallet change')
    previous=response;continue
   if command==('deal' if gid in CLASSIC else 'start'):
    ledger=new_ledger();paid_attempts+=1;round_open=True
   # Price is reconstructed solely from original init, request and native hand.
   cost=request_cost(gid,request,initial,previous);total+=cost
   checked=reconcile(gid,previous,response,request,initial,ledger)
   checks.append(dict(event=index,**checked));verified.add(index)
   if command==('deal' if gid in CLASSIC else 'start'):paid[index]=cost
   if round_open and terminal(gid,response):rounds+=1;round_open=False
   previous=response
  except (ValueError,KeyError,TypeError) as error:
   checks.append(dict(event=index,kind='blackjack_independent_audit',ok=False,error=str(error)));break
 for item in report.get('modes',[]):
  if item.get('status')!='closed':continue
  start=item.get('first_event');end=item.get('last_event');mode=item.get('mode',{})
  ok=(type(start) is int and type(end) is int and start in paid and end in verified and start<=end and terminal(gid,events[end]['response']))
  if ok:
   q=events[start]['request'];commands=[e['request'].get('command') for e in events[start:end+1]];target=mode.get('target','normal')
   ok=mode.get('command')==q.get('command') and mode.get('options')==q.get('options') and mode.get('cost_native')==paid[start]
   if target in ('insurance_accept','insurance_skip'):
    selected=[e['request'].get('options',{}).get('areas') for e in events[start:end+1] if e['request'].get('command')=='insurance']
    ok=ok and any(bool(x)==(target=='insurance_accept') for x in selected)
   else:ok=ok and (target=='normal' or target in commands)
  checks.append(dict(event=end,kind='blackjack_closed_mode_receipt',ok=bool(ok)))
 return dict(game_id=gid,status=report.get('status'),events=len(events),checks=checks,passed=sum(c['ok'] for c in checks),
             failed=sum(not c['ok'] for c in checks),paid_attempts=paid_attempts,rounds=rounds,cost_native=total,
             modes_closed=sum(m.get('status')=='closed' for m in report.get('modes',[])))
