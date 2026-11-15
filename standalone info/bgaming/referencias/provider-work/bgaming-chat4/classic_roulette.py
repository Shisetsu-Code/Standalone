"""Classic roulette native array bets and mandatory finish; one representative per type."""
import hashlib
GAMES=['AmericanRoulette','EuropeanRoulette','FrenchRoulette']
POSITIONS={'straight_up':['1'],'split':['0','1'],'street':['1','2','3'],'trio':['0','1','2'],'basket':['0','1','2'],'corner':['1','2','4','5'],'line':['1','2','3','4','5','6'],'column':['0'],'dozen':['0'],'red':None,'black':None,'low':None,'high':None,'odd':None,'even':None,'first_four':None,'first_five':None}
def metadata(gid,source):
 if gid not in GAMES or 'My.games.'+gid+'=' not in source:raise ValueError('Classic roulette registration absent')
 proof=['bet_id:o,type:a[0],bet:a[1].split(","),amount:e','{command:"spin",options:r}','{command:"finish"}','e.result.total/t.options.currency.subunits','basket-0,1,2','trio-0,1,2','column-0','dozen-0','"corner-"+A.toString()','"line-"+A.toString()','"street-"+A.toString()','split-0,1','straight_up-']
 if not all(token in source for token in proof):raise ValueError('Classic roulette request/positions/payout/finish source not proved')
 return dict(classic_roulette_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Shared client registers this game, creates explicit roulette table shapes, sends native array spin.options with bet_id/type/bet/amount, credits result.total and then sends finish.',coverage_limit='One source-valid position per advertised bet type; all coordinate permutations and conditional en-prison outcomes are not exhaustively generated.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];minimum=o['min_bet'];types=o['bet_limits']
 if not meta.get('classic_roulette_verified') or c.get('code')!='FUN' or c.get('subunits')!=100 or type(minimum) is not int or minimum<=0 or type(initial.get('balance')) is not int or 'spin' not in initial.get('available_commands',[]):raise ValueError('Unverified classic roulette FUN initialization')
 if not set(types)<=set(POSITIONS):raise ValueError('New roulette bet type requires source review')
 modes=[]
 for name,maximum in types.items():
  if minimum>maximum:raise ValueError('Advertised roulette minimum exceeds type maximum')
  bet={'bet_id':1,'type':name,'amount':minimum}
  if POSITIONS[name] is not None:bet['bet']=POSITIONS[name]
  modes.append(dict(name=name,protocol='classic-roulette',command='spin',options=[bet],cost_native=minimum))
 return modes
def spin_result(before,response,cost):
 result=response.get('result');win=0 if result is None else result.get('total',0);balance=response.get('balance')
 if any(type(x) is not int for x in [before,cost,win,balance]) or win<0 or 'finish' not in response.get('available_commands',[]):raise ValueError('Classic roulette result/finish state unverified')
 expected=before-cost+win
 if expected!=balance:raise ValueError('Classic roulette native spin balance mismatch')
 return dict(kind='classic_roulette_spin_balance',expected=expected,actual=balance,cost_native=cost,win_native=win,ok=True)
def finish_result(before,response):
 if type(response.get('balance')) is not int or response['balance']!=before['balance'] or 'spin' not in response.get('available_commands',[]):raise ValueError('Classic roulette finish balance/state mismatch')
 return dict(kind='classic_roulette_finish_balance',expected=before['balance'],actual=response['balance'],ok=True)
def run(demo,mode,initial):
 old=demo.prev or initial
 if 'spin' not in old.get('available_commands',[]):raise ValueError('Roulette spin not available')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);r=demo.call('spin',mode['options']);check=spin_result(old['balance'],r,mode['cost_native']);demo.money_checks.append(check);final=demo.call('finish');demo.money_checks.append(finish_result(r,final));demo.prev=final
 return dict(mode=mode,status='closed',first_event=start,last_event=len(demo.events)-1,final_balance=final['balance'],final_state='finished',win_native=check['win_native'])
