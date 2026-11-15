"""Official classic Plinko request and native scalar result; no client balance rewriting."""
import re,hashlib
def metadata(source):
 wire=r'options:\{bet:([A-Za-z_$][\w$]*),risk_level:([A-Za-z_$][\w$]*),rows:([A-Za-z_$][\w$]*)\}'
 if not re.search(wire,source) or not re.search(r'win:[A-Za-z_$][\w$]*\.result,totalBet:',source):raise ValueError('Classic Plinko wire/result not proved')
 return dict(classic_plinko_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Official playGame request bet/risk_level/rows; PLAY win uses native response.result; native balance checked independently')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];table=initial.get('paytable',{});minimum=o.get('min_bet');risks=o.get('risk_levels',[])
 if not meta.get('classic_plinko_verified') or c.get('code')!='FUN' or c.get('subunits')!=100 or type(initial.get('balance')) is not int or type(minimum) is not int or minimum<=0 or 'play' not in initial.get('available_commands',[]):raise ValueError('Unverified classic Plinko initial state')
 if set(risks)!={'low','medium','high'} or set(table)!=set(map(str,range(8,17))):raise ValueError('Unverified classic Plinko risk/row range')
 modes=[]
 for risk in risks:
  for row in sorted(table,key=int):
   if len(table[row].get(risk,[]))!=int(row)+1:raise ValueError('Plinko payout table dimension mismatch')
   modes.append(dict(name=f'risk:{risk}/rows:{row}',protocol='legacy-plinko',command='play',options={'bet':minimum,'risk_level':risk,'rows':int(row)},cost_native=minimum))
 return modes
def closed_result(before,response,cost):
 if response.get('game',{}).get('state')!='closed':raise ValueError('Unrecognized Plinko continuation; native response retained')
 win=response.get('result');balance=response.get('balance')
 if any(type(v) is not int for v in [before,cost,win,balance]) or win<0:raise ValueError('Unverified native Plinko amount schema')
 expected=before-cost+win
 if balance!=expected:raise ValueError('Classic Plinko native wallet mismatch')
 return dict(status='closed',final_balance=balance,final_state='closed',win_native=win,check=dict(kind='classic_plinko_native_balance',cost_native=cost,win_native=win,expected=expected,actual=balance,ok=True))
def run_mode(demo,mode,initial):
 old=demo.prev or initial
 if mode['command'] not in old.get('available_commands',[]):raise ValueError('Plinko play not currently advertised')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);response=demo.call(mode['command'],mode['options']);result=closed_result(old['balance'],response,mode['cost_native']);demo.money_checks.append(result.pop('check'));demo.prev=response
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
