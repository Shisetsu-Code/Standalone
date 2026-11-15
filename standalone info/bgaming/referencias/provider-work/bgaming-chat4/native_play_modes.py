"""Source-verified non-slot mode selectors; native bet and bets.initial/win_amount."""
import re,hashlib
CONTRACTS={'DiceClash':('game_mode','game_types'),'StreetPower':('game_type','game_types'),'FortuneSpin':('game_mode','game_modes')}
def metadata(gid,source):
 if gid not in CONTRACTS:raise ValueError('Unverified native play game')
 field,key=CONTRACTS[gid]
 assignment=(r'additionalPlayData\.'+field+r'=' if field=='game_mode' else r'additionalPlayData=\{game_type:')
 if not re.search(assignment,source) or 'options:{bet:' not in source or 'bonus:!!' not in source or '.data.additionalPlayData}})' not in source or '.bets.win_amount' not in source or '.options.line_bets_cents' not in source:raise ValueError('Native play source selector/bet/payout not proved')
 if not re.search(r'\.playCommand="play"',source):raise ValueError('Native play command override missing')
 return dict(native_play_selector=field,native_play_catalog_key=key,source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Official client sets additionalPlayData selector, takes native bet list from options.line_bets_cents and sends play with bet/bonus/additionalPlayData. Native bets.initial and bets.win_amount checked independently.',coverage_limit='All advertised mode selectors once at their minimum native stake; arbitrary stake sizes and chance-dependent persistent progress states are not exhaustively enumerated.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];modes=o[meta['native_play_catalog_key']];bets=o['line_bets_cents']
 if c.get('code')!='FUN' or c.get('subunits')!=100 or type(initial.get('balance')) is not int or 'play' not in initial.get('available_commands',[]) or not isinstance(modes,list) or not modes:raise ValueError('Unverified native mode initial schema')
 result=[]
 for value in modes:
  available=bets[value] if isinstance(bets,dict) else bets;minimum=min(available)
  if type(value) is not str or type(minimum) is not int or minimum<=0:raise ValueError('Unverified native mode minimum')
  result.append(dict(name=value,protocol='native-play-modes',command='play',options={'bet':minimum,'bonus':False,meta['native_play_selector']:value},cost_native=minimum))
 return result
def settled(before,response,cost):
 b=response.get('bets',{});bet=b.get('initial');win=b.get('win_amount');balance=response.get('balance')
 if response.get('game',{}).get('state')!='closed' or any(type(x) is not int for x in [before,bet,win,balance,cost]) or bet!=cost or win<0:raise ValueError('Native play terminal/stake/payout needs review')
 expected=before-cost+win
 if expected!=balance:raise ValueError('Native play balance mismatch')
 return dict(status='closed',final_balance=balance,final_state='closed',win_native=win,check=dict(kind='native_play_balance',expected=expected,actual=balance,cost_native=cost,win_native=win,ok=True))
def run(demo,mode,initial):
 old=demo.prev or initial
 if 'play' not in old.get('available_commands',[]):raise ValueError('Native play not currently advertised')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);response=demo.call('play',mode['options']);result=settled(old['balance'],response,mode['cost_native']);demo.money_checks.append(result.pop('check'));demo.prev=response
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
