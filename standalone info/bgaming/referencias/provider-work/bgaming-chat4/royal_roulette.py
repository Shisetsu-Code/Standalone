"""Royal Roulette 500X uses bets with type/amount/optional feature, not classic bet arrays."""
import hashlib
from fractions import Fraction
FEATURES={'straight_up':'1','split':'0,3','street':'1,2,3','corner':'1,2,4,5','line':'1,2,3,4,5,6','column':'1','dozen':'1','red':None,'black':None,'odd':None,'even':None,'lows':None,'highs':None}
def metadata(source):
 proof=['get requestPlayData()','e.push({amount:t.viewBet,','type:t.linkedSegment.type','{feature:t.linkedSegment.feature}','additionalPlayData={bets:t,bonus:void 0}','feature:(a+1).toString()','(3-e).toString()','feature:"0,3"','.bets.win_amount']
 if not all(t in source for t in proof):raise ValueError('Royal Roulette native wire/feature indexing not proved')
 return dict(royal_roulette_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Royal controller requestPlayData emits type/amount/optional feature. Dozen and column features are one-based; standard geometry uses comma-separated feature strings. Payout is native bets.win_amount.',coverage_limit='One valid representative per advertised native type; composite track/neighbor placements and coordinate permutations are not exhaustively enumerated.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];minimum=o['min_bet'];types=o['bet_types']
 if not meta.get('royal_roulette_verified') or c.get('code')!='FUN' or c.get('subunits')!=100 or type(minimum) is not int or minimum<=0 or not set(types)<=set(FEATURES) or type(initial.get('balance')) is not int or 'play' not in initial.get('available_commands',[]):raise ValueError('Royal Roulette FUN schema not verified')
 modes=[]
 for name in types:
  bet={'type':name,'amount':minimum}
  if FEATURES[name] is not None:bet['feature']=FEATURES[name]
  modes.append(dict(name=name,protocol='royal-roulette',command='play',options={'bets':[bet]},cost_native=minimum))
 return modes
def settled(before,response,cost):
 win=response.get('bets',{}).get('win_amount');balance=response.get('balance')
 if response.get('game',{}).get('state')!='closed' or any(type(v) not in [int,float] for v in [before,cost,win,balance]) or win<0:raise ValueError('Royal Roulette terminal/payout schema needs review')
 expected=Fraction(str(before))-Fraction(str(cost))+Fraction(str(win))
 if expected!=Fraction(str(balance)):raise ValueError('Royal Roulette native balance mismatch')
 return dict(status='closed',final_balance=balance,final_state='closed',win_native=win,check=dict(kind='royal_roulette_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual=balance,cost_native=cost,win_native=win,ok=True))
def run(demo,mode,initial):
 old=demo.prev or initial
 if 'play' not in old.get('available_commands',[]) and old.get('game',{}).get('state')=='closed' and 'init' in old.get('available_commands',[]):
  before=old;index=len(demo.events);old=demo.call('init');demo.events[-1]['kind']='non_wagering_between_closed_rounds_init'
  if old.get('balance')!=before['balance']:demo.provider_state_observations=getattr(demo,'provider_state_observations',[])+[dict(kind='native_init_balance_change',event=index,before_native=before['balance'],after_native=old.get('balance'),note='Native provider init between closed rounds. Not a gameplay win, local top-up or retroactive correction.')]
  demo.prev=old
 if 'play' not in old.get('available_commands',[]):raise ValueError('Royal Roulette play not available')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);r=demo.call('play',mode['options']);result=settled(old['balance'],r,mode['cost_native']);demo.money_checks.append(result.pop('check'));demo.prev=r
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
