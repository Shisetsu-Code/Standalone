"""Source-gated non-slot FUN actions. No network occurs at import or planning.

Wallet and held game money remain separate original native values. Conditional
actions require actual advertisement; synthetic verification never implies live QA.
"""
import hashlib
import re
from fractions import Fraction

SUPPORTED=('InfinityPull','ChickenRush2','PenaltyDuel','PenaltyDuelWithJulioCesar',
           'FishingTime','ElementsOfPower','JogoDoBicho','TileMaster')


def metadata(source,gid):
 if gid not in SUPPORTED:raise ValueError('Unsupported native client')
 shared=[r'options.currency.subunits',r'\.balance.game>0&&"closed"===.*?\.balance.wallet\+=.*?\.balance.game']
 custom={
 'InfinityPull':[r'additionalPlayData=\{game_mode:',r'\{red:"low",blue:"medium",yellow:"high"\}',r'playCommand="freespin"===\w+.game.state\?"freespin":"play"',r'bets.win_amount-\w+.bets.initial',r'options.game_modes',r'options.line_bets',r'getCurrentBetMultiplier\(\)\{.{0,180}?gameModes.{0,70}?\[\w+\]',r'getChildByName\("bet-list-button"\).totalBet=1!==.{0,100}?\?\w+\*.*?getCurrentBetMultiplier\(\):0',r'onBetListButtonClick\(.{0,200}?data.totalBet=\w+'],
 'ChickenRush2':[r'new Set\(\["play","freespin"\]\)',r'_buildPlayPayload\(\w+\)',r'game_mode:',r'\?\?"easy"',r'PLAY:"play",SPIN:"spin",CASHOUT:"cashout"',r'\}\}:\{command:\w+\}',r'options.currency',r'win_amount'],
 'PenaltyDuel':[r'additionalPlayData=\{game_mode:',r'sector:\w+,high_chance_buy:this.bonusChanceMode',r'"bonus_state"===.*?\?"bonus_play":"play"',r'playCommand="bonus_buy"',r'purchased_features_multipliers.buy_bonus',r'purchased_features_multipliers.high_chance_buy',r'bets.win_amount',r'playGame\(\w+=null\)',r'(?:selectRandomSector\(\).onInteractionDown|this.netButtons\[Math.floor\(Math.random\(\)\*this.netButtons.length\)\].{0,220}?onInteractionDown)',r'currentScene.playGame\(this.id\)'],
 'FishingTime':[r'_installCustomRequestShapes\(\)',r'var \w+,\w+=\{bets:',r'request\(\{command:"play",options:\w+\}',r'"white-bet":"white","dark-bet":"grey","big-bet":"blue","huge-bet":"yellow","mega-bet":"red"',r'_collectSectorBets\(\)',r'\w+\[\w+\]=\w+',r'bets.*?win_amount'],
 'ElementsOfPower':[r'api.playGame=function\(\)',r'void 0===\w+\[\w+\]\?delete',r'bet:"play"===.*?\?[^:]+:void 0,bonus:void 0',r'command:"cashout",options:',r'command:"partial_cashout",options:',r'command:"finish"',r'cashout\(\)\{.*?cashoutAction\(\)\}',r'partialCashout\(\)\{.*?partialCashoutAction\(\)\}',r'playCommand=.*?\?"spin":"play"',r'bets.win_amount'],
 'JogoDoBicho':[r'var \w+=\{bets:\w+\}',r'command:"play",options:',r'getBetsData\(\)',r'\{amount:\w+\[0\].bet\}',r'\.numbers=\w+.map',r'\.animals=\w+.map',r'for\(var \w+ of \w+.bets\)',r'\.win&&',r'isAdvancedBetLengthEqualTo`[234]',r'isBetLengthEqualTo`[12345]'],
 'TileMaster':[r'additionalPlayData.risk_level=this._currentMode',r'changePlayCommand\("start"\)',r'changePlayCommand\("spin"\)',r'changePlayCommand\("stop"\)',r'options.line_bets_cents',r'options.paytables',r'\.bets\).*?win_amount']}
 patterns=shared+custom['PenaltyDuel' if gid.startswith('PenaltyDuel') else gid]
 if gid=='InfinityPull':patterns += [r'initGame\([^)]*\)\{return this.clearSettingsForReplay\(\),this.request\(',r'command:"init"']
 if gid=='ElementsOfPower':patterns += [r'initGame\([^)]*\)\{return this.clearSettingsForReplay\(\),this.request\(',r'command:"init"',r'onInitResponse\(\w+\)\{.{0,600}?data.hasProgress=\w+.game.outcome',r'spin\(\)\{.{0,400}?data.previousBalance=.*?data.balance-.*?data.totalBet',r'getPartialMultiplier\(\w+,\w+\)\{.{0,450}?return Math.round\(1e3\*\(']
 if gid not in ('ChickenRush2','ElementsOfPower','FishingTime','JogoDoBicho'):
  patterns += [r'options:\{bet:.*?bonus:!!.*?\.data.additionalPlayData\}\}']
 proofs=[]
 for pattern in patterns:
  m=re.search(pattern,source)
  if not m:raise ValueError('Unproved '+gid+' source: '+pattern)
  proofs.append(dict(pattern=pattern,offset=m.start(),excerpt=m.group()))
 details={}
 if gid.startswith('PenaltyDuel'):
  details['sectors']={}
  for role,cls in [('striker','StrikerNetButton'),('goalkeeper','GoalkeeperNetButton')]:
   values=sorted(set(map(int,re.findall(r'c:"'+cls+r'",p:\{[^}]+?id:(\d+)',source))))
   if values:details['sectors'][role]=values
 return dict(native_modes_extra_verified=True,game_id=gid,protocol='native-modes-extra',
             source_sha256=hashlib.sha256(source.encode()).hexdigest(),proofs=proofs,**details)


def integer(value,name):
 if type(value) is not int or value<0:raise ValueError('Unproved native amount '+name)
 return value


def wallet(balance):
 if isinstance(balance,dict):
  integer(balance.get('game',0),'held game');return integer(balance.get('wallet'),'wallet')
 return integer(balance,'balance')


def available(response,command):
 commands=response.get('available_commands',response.get('flow',{}).get('available_actions',[]))
 return bool(commands.get(command)) if isinstance(commands,dict) else command in commands


def state(response):return response.get('game',{}).get('state',response.get('flow',{}).get('state'))


def plan(initial,meta):
 gid=meta.get('game_id');o=initial['options'];c=o['currency']
 if not meta.get('native_modes_extra_verified') or gid not in SUPPORTED or c.get('code')!='FUN' or c.get('subunits')!=100:
  raise ValueError('Unproved FUN native mode contract')
 wallet(initial['balance'])
 if state(initial) not in ('idle','closed'):raise ValueError('Existing native round requires recovery')
 modes=[]
 def add(name,command,options,cost,target='base'):
  integer(cost,'cost')
  if not available(initial,command):raise ValueError('Initial command absent: '+command)
  modes.append(dict(name=name,protocol='native-modes-extra',game_id=gid,command=command,
                    options=options,cost_native=cost,target=target,source_sha256=meta['source_sha256']))
 if gid=='InfinityPull':
  if set(o['game_modes'])!={'low','medium','high'}:raise ValueError('Unknown Infinity mode')
  bet=min(o['line_bets']);integer(bet,'bet')
  for value in o['game_modes']:
   factor=integer(o['game_modes'][value],'Infinity mode multiplier')
   if factor<=0:raise ValueError('Invalid native Infinity mode multiplier')
   for target in ('base','freespin'):
    add(value+'/'+target,'play',dict(bet=bet,bonus=False,game_mode=value),bet*factor,target)
 elif gid=='ChickenRush2':
  if set(o['game_modes'])!={'easy','medium','hard','hardcore'}:raise ValueError('Unknown Chicken mode')
  bet=min(o['line_bets'])
  for value in o['game_modes']:
   for target in ('cashout','spin'):add(value+'/'+target,'play',dict(bet=bet,game_mode=value),bet,target)
 elif gid=='TileMaster':
  if set(o['paytables'])!={'low','medium','high'}:raise ValueError('Unknown Tile risk')
  for value in o['paytables']:
   bet=min(o['line_bets_cents'][value])
   for target in ('stop','spin'):add(value+'/'+target,'start',dict(bet=bet,bonus=False,risk_level=value),bet,target)
 elif gid.startswith('PenaltyDuel'):
  bet=min(o['line_bets']);multipliers=o['purchased_features_multipliers'];disabled=o.get('disabled_features',[])
  for value in o['game_modes']:
   sectors=meta['sectors'].get(value)
   if sectors!=list(range(1,11)):raise ValueError('Unproved Penalty sector UI')
   for chance in (False,True):
    if chance and 'high_chance_buy' in disabled:continue
    cost=Fraction(bet)*Fraction(str(multipliers['high_chance_buy'] if chance else multipliers['main_game']))
    if cost.denominator!=1:raise ValueError('Fractional Penalty native cost')
    for sector in sectors:
     add(f'{value}/chance:{chance}/sector:{sector}','play',dict(bet=bet,bonus=False,game_mode=value,sector=sector,high_chance_buy=chance),int(cost))
  if 'buy_bonus' not in disabled and 'striker' in o['game_modes']:
   cost=Fraction(bet)*Fraction(str(multipliers['buy_bonus']))
   if cost.denominator!=1:raise ValueError('Fractional Penalty purchase cost')
   add('striker/buy_bonus','bonus_buy',dict(bet=bet,bonus=False),int(cost),'bonus_play')
 elif gid=='FishingTime':
  bet=min(o['line_bets']);sectors=list(dict.fromkeys(o['sectors']))
  if set(sectors)!={'white','grey','blue','yellow','red'}:raise ValueError('Unknown Fishing sector')
  for value in sectors:add('sector:'+value,'play',{'bets':{value:bet}},bet)
  for name,values in [('all_bonuses',['blue','yellow','red']),('all_sectors',sectors)]:
   add(name,'play',{'bets':dict.fromkeys(values,bet)},bet*len(values))
 elif gid=='JogoDoBicho':
  bet=o['min_bet'];animals=list(o['animals'])
  if len(animals)!=25 or set(o['paytable']['animals'])!={'simple','dupla','terna','cuadra','quina'}:raise ValueError('Unknown Jogo animal categories')
  for animal in animals:add('animal:'+animal,'play',{'bets':[{'amount':bet,'animals':[animal]}]},bet)
  for count in range(2,6):add('animal_count:'+str(count),'play',{'bets':[{'amount':bet,'animals':animals[:count]}]},bet)
  for count in (2,3,4):add('number_digits:'+str(count),'play',{'bets':[{'amount':bet,'numbers':[str(i) for i in range(count)]}]},bet)
 elif gid=='ElementsOfPower':
  bet=min(o['line_bets'])
  for target in ('cashout','partial_cashout'):
   add(target,'play',{'bet':bet},bet,target)
   modes[-1].update(continuation_cost_native=bet,max_additional_paid_spins=8,max_native_cost=bet*9)
 return modes


def continuation_options(mode,command):
 gid=mode['game_id']
 if gid in ('ChickenRush2','ElementsOfPower'):return None
 if gid=='TileMaster':return dict(mode['options'])
 if gid=='InfinityPull':return dict(mode['options'])
 if gid.startswith('PenaltyDuel') and command=='bonus_play':
  return dict(bet=mode['options']['bet'],bonus=False,game_mode=mode['options'].get('game_mode','striker'),sector=None,high_chance_buy=False)
 raise ValueError('Unproved native continuation')


def payout(response,gid):
 if gid=='JogoDoBicho':
  bets=response.get('bets')
  if not isinstance(bets,list):raise ValueError('Missing native Jogo returned bets')
  return sum(0 if b.get('win') is None else integer(b['win'],'Jogo bet win') for b in bets)
 return integer(response.get('bets',{}).get('win_amount'),'win_amount')


def wallet_check(before_balance,response,cost,credited,gid=None,before_closed=False,command=None):
 if response.get('errors'):raise ValueError('Native server error; retained response')
 before=wallet(before_balance);actual=wallet(response.get('balance'));integer(cost,'cost')
 # Official globalDataHandler credits closed native game money to wallet. Check
 # that native sum without modifying either original field or server response.
 if before_closed and isinstance(before_balance,dict):
  if 'free_rounds' in before_balance:raise ValueError('Promotional wallet settlement is outside native FUN adapter')
  before+=before_balance.get('game',0)
 if state(response)=='closed' and isinstance(response['balance'],dict):
  if 'free_rounds' in response['balance']:raise ValueError('Promotional wallet settlement is outside native FUN adapter')
  actual+=response['balance'].get('game',0)
 released=0
 if gid=='ElementsOfPower' and command=='finish':
  if state(response)!='closed' or not isinstance(before_balance,dict):raise ValueError('Elements finish must release original native held wallet')
  released=integer(before_balance.get('game',0),'held release')
  receipt=response.get('bets',{}).get('win_amount')
  if receipt is not None and integer(receipt,'finish receipt') not in (0,released):raise ValueError('Elements finish receipt differs from native held release')
  win=released
 else:win=payout(response,gid) if credited else 0
 expected=before-cost+win
 if expected!=actual:raise ValueError(f'Native wallet mismatch: expected {expected}, actual {actual}')
 balance=response['balance'];held=balance.get('game',0) if isinstance(balance,dict) else 0
 return dict(kind='native_modes_extra_wallet',expected=expected,actual=actual,actual_wallet_native=wallet(balance),
             cost_native=cost,win_native=win,held_native=held,released_held_native=released,ok=True)


def credited_now(gid,command,response):
 # Source transfers game funds only when closed. A finished Elements cashout
 # still exposes the award in native balance.game, awaiting advertised finish.
 if gid=='ElementsOfPower' and state(response)=='finished':return False
 return (gid in ('InfinityPull','FishingTime','JogoDoBicho') or state(response)=='closed'
         or command in ('cashout','partial_cashout','stop','finish'))


def elements_target_ready(response,target,initial=None):
 """The UI enables partial collection only with a positive native potential."""
 game=response.get('game',{})
 if target=='partial_cashout':
  value=game.get('partial_cashout_potential_multiplier')
  if type(value) in (int,float) and value>0:return True
  # The official core controller computes the partial button from progress and
  # the original pay table, even when the optional API multiplier is absent.
  progress=game.get('outcome',{}).get('state',{});table=(initial or {}).get('options',{}).get('pay_table',{})
  if isinstance(progress,dict):
   for color,depth in progress.items():
    entries=table.get(color,[])
    if type(depth) is int and 2<=depth<=len(entries):
     current,prior=entries[depth-1],entries[depth-2]
     if type(current) in (int,float) and type(prior) in (int,float) and round((current-prior)*1000)>0:return True
  return False
 progress=game.get('outcome',{}).get('state',{})
 return isinstance(progress,dict) and any(type(v) is int and v>0 for v in progress.values())


def _infinity_refresh_valid(initial,response):
 o=initial['options'];fresh=response.get('options',{});currency=fresh.get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100 or fresh.get('game_modes')!=o['game_modes'] or fresh.get('line_bets')!=o['line_bets']:
  raise ValueError('Infinity native init changed currency or source wager prices')
 wallet(response.get('balance'))
 if state(response) not in ('idle','closed') or not available(response,'play'):raise ValueError('Infinity init did not advertise a fresh paid play state')


def _refresh_infinity_closed(demo,current,initial):
 if state(current)!='closed' or available(current,'play') or not available(current,'init'):raise ValueError('Infinity refresh requires closed init-only native state')
 before=wallet(current['balance']);response=demo.call('init');demo.prev=response
 _infinity_refresh_valid(initial,response);after=wallet(response['balance'])
 demo.money_checks.append(dict(kind='native_fun_balance_refresh',before_native=before,after_native=after,
                               delta_native=after-before,not_gameplay=True,ok=True,
                               evidence='Advertised non-wagering init after native closed state; original FUN response becomes fresh actual baseline'))
 return response


def _elements_spin_price(initial,active_options,previous):
 if not isinstance(active_options,dict) or set(active_options)!={'bet'}:raise ValueError('Elements spin lacks original retained wager')
 bet=integer(active_options['bet'],'retained Elements base bet')
 if not bet or bet not in initial['options']['line_bets']:raise ValueError('Retained Elements bet outside original native list')
 receipt=previous.get('bets',{}).get('initial')
 if receipt is not None and receipt!=bet:raise ValueError('Elements native retained bet differs from original paid request')
 return bet


def _elements_continue(demo,mode,initial,current,start,reached=False,used_paid_spins=0):
 """Bounded explicit paid progression; omitted spin.bet retains the base wager."""
 bet=_elements_spin_price(initial,mode['options'],current);limit=mode.get('max_additional_paid_spins',8)
 if type(limit) is not int or not 0<=limit<=64:raise ValueError('Invalid explicit Elements paid-spin budget')
 target=mode['target']
 for _ in range(64):
  if state(current)=='closed':break
  if available(current,'finish'):
   if state(current)!='finished':raise ValueError('Elements finish requires native finished held-wallet stage')
   command='finish'
  elif not reached and available(current,target) and elements_target_ready(current,target,initial):command=target
  elif reached and available(current,'cashout'):command='cashout'
  elif not reached and available(current,'spin') and used_paid_spins<limit and wallet(current['balance'])>=bet:command='spin'
  elif available(current,'cashout'):command='cashout'
  else:raise ValueError('No bounded source-proved Elements collection/continuation')
  before=current;cost=_elements_spin_price(initial,mode['options'],before) if command=='spin' else 0
  response=demo.call(command);demo.prev=response;current=response
  if response.get('game',{}).get('action') not in (None,command):raise ValueError('Elements native response action differs from requested action')
  demo.money_checks.append(wallet_check(before['balance'],response,cost,credited_now('ElementsOfPower',command,response),
                                       'ElementsOfPower',command=command))
  if command=='spin':used_paid_spins+=1
  if command==target:reached=True
 else:raise ValueError('Elements continuation bound exhausted; raw pending receipt retained')
 if state(current)!='closed':raise ValueError('Elements native closure not proved')
 return dict(mode=mode,status='closed' if reached else 'needs_trigger',first_event=start,last_event=len(demo.events)-1,
             final_balance=current['balance'],final_state='closed',additional_paid_spins=used_paid_spins,
             additional_cost_native=used_paid_spins*bet,total_mode_cost_native=bet*(1+used_paid_spins))


def run(demo,mode,initial):
 """One paid attempt; at most 64 source-proved unpaid continuation commands.

 Partial payout and cumulative held award fields are not interchangeable. Unknown
 schemas fail after recording exact response, with no automatic retry or re-init.
 """
 gid=mode.get('game_id')
 if mode.get('protocol')!='native-modes-extra' or gid not in SUPPORTED:raise ValueError('Unproved native mode')
 current=demo.prev or initial
 if state(current) not in ('idle','closed'):raise ValueError('Unresolved preceding native round')
 if gid=='InfinityPull' and state(current)=='closed' and not available(current,'play'):
  current=_refresh_infinity_closed(demo,current,initial)
 spendable=wallet(current['balance'])
 if isinstance(current['balance'],dict):
  if 'free_rounds' in current['balance']:raise ValueError('Promotional wallet requires separate review')
  spendable+=current['balance'].get('game',0)
 if spendable<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);target=mode['target'];reached=target=='base';count=0
 def send(command,options=None,cost=0):
  nonlocal current,count
  if not available(current,command):raise ValueError('Native command not advertised: '+command)
  before=current['balance'];before_closed=state(current) in ('idle','closed')
  response=demo.call(command,options) if options is not None else demo.call(command)
  demo.prev=response;current=response;count+=1
  if gid=='InfinityPull' and cost and response.get('bets',{}).get('initial')!=cost:
   raise ValueError('Infinity native debit does not match source-proved mode multiplier')
  credited=credited_now(gid,command,response)
  demo.money_checks.append(wallet_check(before,response,cost,credited,gid,before_closed=before_closed,command=command))
 send(mode['command'],mode['options'],mode['cost_native'])
 if gid=='ElementsOfPower':return _elements_continue(demo,mode,initial,current,start)
 for _ in range(64):
  if state(current)=='closed' and not (gid=='ElementsOfPower' and available(current,'finish')):break
  if gid=='InfinityPull' and available(current,'freespin'):
   send('freespin',continuation_options(mode,'freespin'));reached=True
  elif gid.startswith('PenaltyDuel') and available(current,'bonus_play'):
   send('bonus_play',continuation_options(mode,'bonus_play'));reached=True
  elif gid in ('ChickenRush2','TileMaster'):
   collect='cashout' if gid=='ChickenRush2' else 'stop'
   if target=='spin' and not reached and available(current,'spin'):
    send('spin',continuation_options(mode,'spin'));reached=True
   elif available(current,collect):
    send(collect,continuation_options(mode,collect));reached=reached or target==collect
   else:raise ValueError('No proved native continuation or collection command')
  else:raise ValueError('Native outcome requires unsupported continuation')
 else:raise ValueError('Native continuation bound exhausted; unresolved response retained')
 if state(current)!='closed':raise ValueError('Native round closure not proved')
 return dict(mode=mode,status='closed' if reached else 'needs_trigger',final_state='closed',
             final_balance=current['balance'],first_event=start,last_event=len(demo.events)-1)


def resume_remaining(demo,modes,initial):
 """Yield each remaining Infinity result for parent checkpoint before next wager."""
 if any(m.get('game_id')!='InfinityPull' or m.get('protocol')!='native-modes-extra' for m in modes):raise ValueError('Remaining recovery is restricted to explicit Infinity modes')
 current=getattr(demo,'last_response',None) or demo.prev
 if current is None or state(current)!='closed' or not available(current,'init') or available(current,'play'):
  raise ValueError('Remaining recovery requires received closed Infinity init-only state')
 demo.prev=current
 for mode in modes:yield run(demo,mode,initial)


def _elements_received_refresh_valid(initial,cashout,response):
 """Only wallet may refresh; pending native game, held prize and identity persist."""
 fresh=response.get('options',{});original=initial['options'];currency=fresh.get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100 or any(fresh.get(k)!=original.get(k) for k in ('line_bets','game_modes','pay_table')):
  raise ValueError('Received Elements init changed source prices or FUN currency')
 # Native action echoes the read command. Source onInitResponse restores from
 # game.outcome, not the action label; every other pending game field must match.
 old_game={k:v for k,v in cashout.get('game',{}).items() if k!='action'}
 new_game={k:v for k,v in response.get('game',{}).items() if k!='action'}
 if new_game!=old_game or state(response)!='finished' or response.get('game',{}).get('action') not in ('cashout','init') or not available(response,'finish') or available(response,'play'):
  raise ValueError('Received Elements init changed pending cashout state')
 if not isinstance(response.get('balance'),dict) or response['balance'].get('game')!=cashout['balance'].get('game') or 'free_rounds' in response['balance']:
  raise ValueError('Received Elements init changed native held prize')
 wallet(response['balance'])
 for key in ('round_id','id','round_series_id'):
  old=cashout.get('flow',{}).get(key);new=response.get('flow',{}).get(key)
  if old!=new:raise ValueError('Received Elements init changed open native round identity')
 old_bet=cashout.get('bets',{}).get('initial');new_bet=response.get('bets',{}).get('initial')
 if old_bet is not None and new_bet is not None and old_bet!=new_bet:raise ValueError('Received Elements init changed pending original wager')


def resume_received(demo,mode,initial):
 """Parent-only recovery of an already received Elements cashout; finish once.

 No initial wager or cashout is replayed. Original event request/response identity,
 native held prize and the preceding response are checked before any transport.
 """
 if mode.get('protocol')!='native-modes-extra' or mode.get('game_id')!='ElementsOfPower':raise ValueError('Received recovery is restricted to Elements cashout')
 currency=initial.get('options',{}).get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Received recovery requires original native FUN init')
 events=demo.events
 if len(events)<2:raise ValueError('Received cashout lacks preceding original event')
 latest=events[-1];current=getattr(demo,'last_response',None) or demo.prev;cashout_index=len(events)-1
 refreshed=latest.get('request',{}).get('command')=='init'
 if refreshed:
  if latest.get('request',{}).get('options') is not None or len(events)<3:raise ValueError('Expected full ordinary Elements init read after received cashout')
  cashout_index-=1
 cashout_event=events[cashout_index];cashout=cashout_event.get('response',{})
 if latest.get('status')!=200 or latest.get('response')!=current or cashout_event.get('status')!=200 or cashout_event.get('request',{}).get('command')!='cashout' or state(cashout)!='finished' or cashout.get('game',{}).get('action')!='cashout' or not available(cashout,'finish') or available(cashout,'play'):
  raise ValueError('Not the exact received finished cashout awaiting finish')
 if refreshed:
  if not available(cashout,'init'):raise ValueError('Read init was not advertised by original cashout')
  _elements_received_refresh_valid(initial,cashout,current)
 paid=[i for i,e in enumerate(events[:cashout_index]) if e.get('request',{}).get('command')=='play']
 if not paid:raise ValueError('Received cashout lacks original paid request')
 start=paid[-1]
 if events[start]['request'].get('options')!=mode['options']:raise ValueError('Received original wager differs from supplied mode')
 previous=events[cashout_index-1]['response']
 if not available(previous,'cashout'):raise ValueError('Received cashout was not previously advertised')
 before=current['balance']
 if not isinstance(cashout.get('balance'),dict) or integer(cashout['balance'].get('game'),'received held game')!=payout(cashout,'ElementsOfPower'):
  raise ValueError('Received cashout prize differs from native held wallet')
 check=wallet_check(previous['balance'],cashout,0,False,'ElementsOfPower',before_closed=state(previous) in ('idle','closed'),command='cashout')
 check['normalized_received']=True;check['normalized_received_event']=cashout_index
 if not any(c.get('normalized_received_event')==check['normalized_received_event'] for c in demo.money_checks):demo.money_checks.append(check)
 if refreshed:
  old_wallet=wallet(cashout['balance']);fresh_wallet=wallet(current['balance'])
  demo.money_checks.append(dict(kind='native_fun_balance_refresh',before_native=old_wallet,after_native=fresh_wallet,
                               delta_native=fresh_wallet-old_wallet,not_gameplay=True,ok=True,
                               evidence='Explicit received init retains exact pending cashout/game/held prize and FUN source prices'))
 demo.active_mode=mode;demo.prev=current
 response=demo.call('finish');demo.prev=response
 demo.money_checks.append(wallet_check(before,response,0,True,'ElementsOfPower',command='finish'))
 if state(response)!='closed':raise ValueError('Received cashout finish did not close natively')
 fired={e.get('request',{}).get('command') for e in events[start:]}
 # Parent Demo retains request events; fake transports may retain only response.
 fired.add('finish')
 return dict(mode=mode,status='closed' if mode['target'] in fired else 'needs_trigger',
             first_event=start,last_event=len(demo.events)-1,final_balance=response['balance'],
             final_state='closed',normalized_existing_received_cashout=True)


def resume_received_spin(demo,mode,initial):
 """Normalize one already received paid Elements spin, then continue without replay."""
 if mode.get('protocol')!='native-modes-extra' or mode.get('game_id')!='ElementsOfPower' or mode.get('target')!='partial_cashout':raise ValueError('Received spin recovery requires explicit Elements partial target')
 events=demo.events;current=getattr(demo,'last_response',None) or demo.prev
 if len(events)<2 or events[-1].get('status')!=200 or events[-1].get('request',{}).get('command')!='spin' or events[-1].get('request',{}).get('options') is not None or events[-1].get('response')!=current or state(current)!='active' or current.get('game',{}).get('action')!='spin':
  raise ValueError('Not exact accepted native active spin receipt')
 currency=initial.get('options',{}).get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Received spin recovery requires original FUN units')
 paid=[i for i,e in enumerate(events[:-1]) if e.get('request',{}).get('command')=='play']
 if not paid:raise ValueError('Received spin lacks original retained wager')
 start=paid[-1]
 if events[start]['request'].get('options')!=mode['options']:raise ValueError('Received spin original paid mode differs')
 previous=events[-2]['response']
 if not available(previous,'spin'):raise ValueError('Received spin was not previously advertised')
 cost=_elements_spin_price(initial,events[start]['request']['options'],previous)
 checked=wallet_check(previous['balance'],current,cost,credited_now('ElementsOfPower','spin',current),'ElementsOfPower',command='spin')
 checked.update(normalized_received_spin=True,normalized_received_spin_event=len(events)-1)
 if not any(c.get('normalized_received_spin_event')==len(events)-1 for c in demo.money_checks):demo.money_checks.append(checked)
 used=sum(e.get('request',{}).get('command')=='spin' for e in events[start:])
 reached=any(e.get('request',{}).get('command')==mode['target'] for e in events[start:])
 demo.prev=current;demo.active_mode=mode
 return _elements_continue(demo,mode,initial,current,start,reached,used)


def _audit_request_price(gid,request,initial,previous,active_request):
 """Derive price from wire fields and original init, never runner mode/checks."""
 command=request.get('command');args=request.get('options');o=initial['options']
 paid=command in (('start',) if gid=='TileMaster' else ('play','bonus_buy') if gid.startswith('PenaltyDuel') else ('play',))
 if paid and state(previous) not in ('idle','closed'):
  raise ValueError('Paid request inside unresolved native round')
 if not paid and active_request is None:raise ValueError('Continuation lacks preceding paid request')
 def shape(keys):
  if not isinstance(args,dict) or set(args)!=set(keys):raise ValueError('Unproved '+gid+' '+str(command)+' option shape')
 def raw_bet(values):
  value=integer(args.get('bet'),'request bet')
  if not value or value not in values:raise ValueError('Request bet not in original native wager list')
  return value
 def no_bonus():
  if args.get('bonus') is not False:raise ValueError('Promotional wager outside independent native audit')
 def rational_price(bet,factor):
  if type(factor) not in (int,float) or factor<=0:raise ValueError('Invalid source price multiplier')
  price=Fraction(bet)*Fraction(str(factor))
  if price.denominator!=1:raise ValueError('Fractional native request cost')
  return int(price)
 if gid=='InfinityPull':
  if command not in ('play','freespin'):raise ValueError('Unproved Infinity audit command')
  shape(('bet','bonus','game_mode'));no_bonus();bet=raw_bet(o['line_bets']);value=args['game_mode']
  if value not in o['game_modes']:raise ValueError('Unadvertised Infinity mode')
  if command=='freespin':
   if state(previous)!='freespin' or args!=active_request['options']:raise ValueError('Infinity freespin does not match active native round')
   return 0,False
  return rational_price(bet,o['game_modes'][value]),True
 if gid=='ChickenRush2':
  if command=='play':
   shape(('bet','game_mode'));bet=raw_bet(o['line_bets'])
   if args['game_mode'] not in o['game_modes']:raise ValueError('Unadvertised Chicken game mode')
   return bet,True
  if command not in ('spin','cashout') or args is not None or state(previous)!='active':raise ValueError('Unproved Chicken continuation')
  return 0,False
 if gid=='TileMaster':
  if command not in ('start','spin','stop'):raise ValueError('Unproved Tile audit command')
  shape(('bet','bonus','risk_level'));no_bonus();risk=args['risk_level']
  if risk not in o['line_bets_cents']:raise ValueError('Unadvertised Tile risk')
  bet=raw_bet(o['line_bets_cents'][risk])
  if not paid and (state(previous)!='alive' or args!=active_request['options']):raise ValueError('Tile continuation differs from active native round')
  return (bet if paid else 0),paid
 if gid.startswith('PenaltyDuel'):
  if command=='bonus_buy':
   shape(('bet','bonus'));no_bonus();bet=raw_bet(o['line_bets'])
   if 'buy_bonus' in o.get('disabled_features',[]) or 'striker' not in o['game_modes']:raise ValueError('Disabled native Penalty purchase')
   return rational_price(bet,o['purchased_features_multipliers']['buy_bonus']),True
  if command not in ('play','bonus_play'):raise ValueError('Unproved Penalty audit command')
  shape(('bet','bonus','game_mode','sector','high_chance_buy'));no_bonus();bet=raw_bet(o['line_bets']);value=args['game_mode'];sector=args['sector'];chance=args['high_chance_buy']
  if value not in o['game_modes'] or type(chance) is not bool:raise ValueError('Unadvertised Penalty mode/chance')
  if sector is not None and (type(sector) is not int or not 1<=sector<=len(o['pay_tables'][value+'_normal'])):raise ValueError('Unproved Penalty sector')
  if command=='bonus_play':
   previous_args=active_request['options']
   if state(previous)!='bonus_state' or chance or sector is not None or bet!=previous_args['bet'] or value!=previous_args.get('game_mode','striker'):
    raise ValueError('Penalty unpaid shot differs from active bonus')
   return 0,False
  if sector is None:raise ValueError('Base Penalty play must use the selected source button sector')
  if chance and 'high_chance_buy' in o.get('disabled_features',[]):raise ValueError('Disabled Penalty ante')
  key='high_chance_buy' if chance else 'main_game'
  return rational_price(bet,o['purchased_features_multipliers'][key]),True
 if gid=='FishingTime':
  if command!='play':raise ValueError('Unproved Fishing audit command')
  shape(('bets',));bets=args['bets'];minimum=min(o['line_bets'])
  if not isinstance(bets,dict) or not bets or not set(bets)<=set(o['sectors']):raise ValueError('Unadvertised Fishing sector bet')
  cost=0
  for amount in bets.values():
   amount=integer(amount,'Fishing component')
   if not amount or amount%minimum:raise ValueError('Fishing component not composed of native chips')
   cost+=amount
  return cost,True
 if gid=='JogoDoBicho':
  if command!='play':raise ValueError('Unproved Jogo audit command')
  shape(('bets',));bets=args['bets']
  if not isinstance(bets,list) or not bets:raise ValueError('Missing Jogo native bet list')
  cost=0
  for bet in bets:
   if not isinstance(bet,dict) or set(bet) not in ({'amount','animals'},{'amount','numbers'}):raise ValueError('Unproved Jogo bet shape')
   amount=integer(bet['amount'],'Jogo component')
   if not o['min_bet']<=amount<=o['max_bet'] or amount%o['min_bet']:raise ValueError('Jogo wager outside native limits')
   if 'animals' in bet:
    values=bet['animals']
    if not isinstance(values,list) or not 1<=len(values)<=5 or len(set(values))!=len(values) or not set(values)<=set(o['animals']):raise ValueError('Unproved Jogo animal selection')
   else:
    values=bet['numbers']
    if not isinstance(values,list) or len(values) not in (2,3,4) or any(type(x) is not str or not re.fullmatch('[0-9]',x) for x in values):raise ValueError('Unproved Jogo number digits')
   cost+=amount
  return cost,True
 if gid=='ElementsOfPower':
  if command=='play':shape(('bet',));return raw_bet(o['line_bets']),True
  if command not in ('spin','cashout','partial_cashout','finish') or args is not None:raise ValueError('Unproved Elements continuation shape')
  if state(previous) in ('idle','closed') and command!='finish':raise ValueError('Elements continuation lacks live progress')
  if command=='partial_cashout' and not elements_target_ready(previous,command,initial):raise ValueError('Partial cashout has no source-proved positive potential')
  return (_elements_spin_price(initial,active_request['options'],previous) if command=='spin' else 0),False
 raise ValueError('Unsupported independent native audit family')


def audit(report):
 """Read-only independent wire-price and original native money audit.

 Does not call plan, run, or wallet_check, or trust report checks/mode prices.
 Original init anchors prices; later init cannot silently reset the wallet ledger.
 """
 gid=report.get('game',{}).get('game_id');events=report.get('events',[])
 if gid not in SUPPORTED or not events:raise ValueError('Native audit requires a supported game and original init')
 first=events[0];initial=first.get('response',{});o=initial.get('options',{});currency=o.get('currency',{})
 if first.get('status')!=200 or first.get('request',{}).get('command')!='init' or currency.get('code')!='FUN' or currency.get('subunits')!=100:
  raise ValueError('Native audit requires original FUN init and unit contract')
 def raw_amounts(response):
  balance=response.get('balance')
  if isinstance(balance,dict):
   if 'free_rounds' in balance:raise ValueError('Promotional wallet outside independent native audit')
   return integer(balance.get('wallet'),'raw wallet'),integer(balance.get('game',0),'raw game')
  return integer(balance,'raw balance'),0
 raw_amounts(initial)
 previous=initial;active_request=None;round_open=False;paid_events={};verified_events=set();checks=[dict(event=0,kind='native_initial_schema',ok=True)]
 total_cost=0;paid_attempts=0;rounds=0
 for index,event in enumerate(events[1:],1):
  request=event.get('request',{});response=event.get('response',{});command=request.get('command')
  if event.get('status')!=200:
   checks.append(dict(event=index,kind='native_request_accepted',ok=False,error='Native request not accepted'));continue
  try:
   if response.get('errors'):raise ValueError('Native server returned errors')
   if not available(previous,command):raise ValueError('Command not advertised by preceding original response')
   before_wallet,before_held=raw_amounts(previous);after_wallet,after_held=raw_amounts(response)
   before=before_wallet+(before_held if state(previous) in ('idle','closed') else 0)
   actual=after_wallet+(after_held if state(response)=='closed' else 0)
   if command=='init':
    if gid=='InfinityPull' and state(previous)=='closed' and not available(previous,'play'):
     _infinity_refresh_valid(initial,response)
     checks.append(dict(event=index,kind='native_fun_balance_refresh',before_native=before,after_native=actual,
                        delta_native=actual-before,not_gameplay=True,ok=True));previous=response;active_request=None;continue
    if gid=='ElementsOfPower' and state(previous)=='finished' and previous.get('game',{}).get('action')=='cashout':
     _elements_received_refresh_valid(initial,previous,response)
     checks.append(dict(event=index,kind='native_fun_balance_refresh',before_native=before_wallet,after_native=after_wallet,
                        delta_native=after_wallet-before_wallet,not_gameplay=True,ok=True));previous=response;continue
    if actual!=before:raise ValueError('Init changed native wallet without gameplay settlement')
    checks.append(dict(event=index,kind='native_init_wallet',expected=before,actual=actual,ok=True));previous=response;continue
   cost,paid=_audit_request_price(gid,request,initial,previous,active_request)
   checks.append(dict(event=index,kind='native_request_price',cost_native=cost,paid=cost>0,new_round=paid,ok=True))
   total_cost+=cost
   if paid:
    paid_attempts+=1;paid_events[index]=cost;active_request=request;round_open=True
   credited=(gid in ('InfinityPull','FishingTime','JogoDoBicho') or state(response)=='closed' or command in ('cashout','partial_cashout','stop','finish'))
   if gid=='ElementsOfPower' and state(response)=='finished':credited=False
   win=0
   if gid=='ElementsOfPower' and command=='finish':
    if state(response)!='closed':raise ValueError('Elements finish did not release a closed native wallet')
    win=before_held
    receipt=response.get('bets',{}).get('win_amount')
    if receipt is not None and integer(receipt,'finish receipt') not in (0,win):raise ValueError('Finish receipt differs from original held prize')
   elif credited:
    if gid=='JogoDoBicho':
     returned=response.get('bets')
     if not isinstance(returned,list) or len(returned)!=len(request['options']['bets']):raise ValueError('Jogo response lacks original bet components')
     for original,receipt in zip(request['options']['bets'],returned):
      if any(receipt.get(k)!=v for k,v in original.items()):raise ValueError('Jogo returned wager differs from original request')
      win+=0 if receipt.get('win') is None else integer(receipt['win'],'returned Jogo win')
    else:win=integer(response.get('bets',{}).get('win_amount'),'returned native win')
   if gid=='InfinityPull' and paid and response.get('bets',{}).get('initial')!=cost:raise ValueError('Infinity receipt initial differs from independent multiplied cost')
   expected=before-cost+win
   if expected!=actual:raise ValueError(f'Independent native wallet mismatch: expected {expected}, actual {actual}')
   checks.append(dict(event=index,kind='native_independent_wallet',cost_native=cost,win_native=win,
                      expected=expected,actual=actual,raw_wallet_native=after_wallet,raw_game_native=after_held,ok=True))
   verified_events.add(index)
   if round_open and state(response)=='closed':rounds+=1;round_open=False
   previous=response
  except (ValueError,KeyError,TypeError) as error:
   checks.append(dict(event=index,kind='native_independent_audit',ok=False,error=str(error)))
   break # Do not hide an unknown transition by treating its response as a new anchor.
 for mode in report.get('modes',[]):
  if mode.get('status')!='closed':continue
  first_event=mode.get('first_event');last_event=mode.get('last_event')
  ok=(type(first_event) is int and type(last_event) is int and first_event in paid_events
      and last_event in verified_events and first_event<=last_event and state(events[last_event]['response'])=='closed')
  declared=mode.get('mode')
  if ok and isinstance(declared,dict):
   first_request=events[first_event]['request'];target=declared.get('target','base')
   fired={event.get('request',{}).get('command') for event in events[first_event:last_event+1]}
   ok=(declared.get('command')==first_request.get('command')
       and declared.get('options')==first_request.get('options')
       and declared.get('cost_native')==paid_events[first_event]
       and (target=='base' or target in fired))
  checks.append(dict(event=last_event,kind='native_closed_mode_receipt',ok=ok))
 return dict(game_id=gid,status=report.get('status'),events=len(events),checks=checks,
             passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),
             cost_native=total_cost,paid_attempts=paid_attempts,rounds=rounds,
             modes_closed=sum(x.get('status')=='closed' for x in report.get('modes',[])))
