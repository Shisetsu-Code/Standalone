"""Legacy scalar-balance slots: official SDK line-bet dictionary, no v2 payload rewriting."""
import re,hashlib
def free_spin_wire(source):
 from native_variants import balanced
 for match in re.finditer(r'if\([A-Za-z_$][\w$]*\.isApi2\)(.*?);else\{',source):
  free=re.search(r'([A-Za-z_$][\w$]*)&&\([A-Za-z_$][\w$]*\.command="freespin"\)',match[1])
  if not free:continue
  branch=balanced(source,match.end()-1)
  if not re.search(r'(?<![\w$])'+re.escape(free[1])+r'(?![\w$])',branch) and re.search(r'\.bets=[A-Za-z_$][\w$]*',branch):return True
 return False
def metadata(source):
 expression=r'for\(var ([A-Za-z_$][\w$]*)=([A-Za-z_$][\w$]*)/([A-Za-z_$][\w$]*)\.options\.lines\.length,([A-Za-z_$][\w$]*)=0;\4<\3\.options\.lines\.length;\4\+\+\)([A-Za-z_$][\w$]*)\[\4\]=\1'
 if not re.search(expression,source) or not re.search(r'\.isApi2="2"===[A-Za-z_$][\w$]*\.api_version',source):raise ValueError('Old slot line dictionary request not proved')
 result_total=bool(re.search(r'\.totalWin=([A-Za-z_$][\w$]*)\.result\?\1\.result\.total:0',source))
 buy=bool(re.search(r'this\.getVisibleBet\(\)\*[^;{}]*\.initData\.options\.buy_feature_value',source) and re.search(r'[A-Za-z_$][\w$]*&&\([A-Za-z_$][\w$]*\.buy_feature=!0\)',source))
 cumulative=bool(re.search(r'\.data\.gameTotalWin=.{0,120}\.result.{0,120}\.round_total_win',source))
 return dict(protocol='legacy-v1-slots',source_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),line_bet_contract='UI total stake / count(options.lines), one options.bets[index] entry per line; line_bets are native per-line amounts',finish_command_verified=bool(re.search(r'\.isApi2\?"close":"finish"',source)),v1_result_total_verified=result_total,v1_buy_feature_verified=buy,v1_freespin_spin_verified=free_spin_wire(source),v1_round_total_verified=cumulative)
def plan(initial,meta):
 o=initial['options'];c=o['currency']
 if not meta.get('source_verified') or initial.get('api_version')=='2' or c['code']!='FUN' or c['subunits']!=100 or type(initial.get('balance')) is not int or initial.get('game',{}).get('state')!='idle' or 'spin' not in initial.get('available_commands',[]):raise ValueError('Unverified v1 slot initial state')
 if not o.get('line_bets') or not o.get('lines') or any(type(v) is not int or v<=0 for v in o['line_bets']):raise ValueError('Unverified line stake schema')
 line=min(o['line_bets']);bets={str(i):line for i in range(len(o['lines']))}
 modes=[dict(name='normal/all_default_lines',protocol='legacy-v1-slots',command='spin',options={'bets':bets},line_bet_native=line,line_count=len(bets),cost_native=sum(bets.values()))]
 if o.get('buy_feature_value') and meta.get('v1_buy_feature_verified'):
  value=o['buy_feature_value']
  if type(value) is not int or value<=0:raise ValueError('Unverified native V1 purchase factor')
  modes.append(dict(name='feature_buy',protocol='legacy-v1-slots',command='spin',options={'bets':dict(bets),'buy_feature':True},cost_native=sum(bets.values())*value,native_purchase_factor=value))
 return modes

def paid_result(old,response,mode,meta):
 """Verify native paid-spin amounts independently of whether its bonus/choice is closed."""
 if not meta.get('v1_result_total_verified'):raise ValueError('V1 result.total default not source verified')
 result=response.get('result');win=0 if result is None else result.get('total')
 before=old.get('balance');balance=response.get('balance');cost=mode['cost_native']
 if any(type(v) is not int for v in [before,balance,cost,win]) or win<0:raise ValueError('Unverified native V1 amounts')
 expected=before-cost+win
 if expected!=balance:raise ValueError('V1 native wallet reconciliation mismatch')
 state=response.get('game',{}).get('state')
 return dict(status='closed' if state=='closed' else 'open',final_balance=balance,final_state=state,win_native=win,cost_native=cost,check=dict(kind='v1_native_balance',expected=expected,actual=balance,ok=True,cost_native=cost,win_native=win))

def closed_result(old,response,mode,meta):
 result=paid_result(old,response,mode,meta)
 if result['status']!='closed':raise ValueError('V1 bonus/finish/choice state preserved; continuation requires review')
 return result

def free_result(before,response,options,meta):
 game=before.get('game',{})
 if not meta.get('v1_freespin_spin_verified') or game.get('state')!='freespin' or type(game.get('freespins_left')) is not int or game['freespins_left']<=0 or 'spin' not in before.get('available_commands',[]) or set(options)!={'bets'} or options['bets']!=before.get('bets',{}).get('lines'):raise ValueError('Unverified native V1 free-spin state/request')
 result=response.get('result') or {};old_result=before.get('result') or {}
 if 'total' not in result and 'round_total_win' in result and meta.get('v1_round_total_verified'):
  a=old_result.get('round_total_win');b=result['round_total_win']
  if type(a) is not int or type(b) is not int or b<a or type(before.get('balance')) is not int or type(response.get('balance')) is not int:raise ValueError('Unverified cumulative V1 free-spin amounts')
  win=b-a;expected=before['balance']+win
  if expected!=response['balance']:raise ValueError('Cumulative V1 free-spin delta/wallet mismatch')
  state=response.get('game',{}).get('state');return dict(status='closed' if state=='closed' else 'open',final_state=state,final_balance=response['balance'],win_native=win,win_origin='native_round_total_delta',check=dict(kind='v1_freespin_native_balance',expected=expected,actual=response['balance'],cost_native=0,win_native=win,cumulative_before_native=a,cumulative_after_native=b,ok=True))
 checked=paid_result(before,response,{'cost_native':0},meta);checked['check']['kind']='v1_freespin_native_balance';return checked

def run_mode(demo,mode,initial):
 old=demo.prev or initial
 if mode['command'] not in old.get('available_commands',[]):raise ValueError('V1 command not advertised')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);response=demo.call(mode['command'],mode['options'])
 result=paid_result(old,response,mode,demo.protocol_metadata);demo.money_checks.append(result.pop('check'))
 if result['status']=='open' and response.get('game',{}).get('state')=='check_card' and 'finish' in response.get('available_commands',[]) and demo.protocol_metadata.get('finish_command_verified'):
  from classic_gamble import check_finish
  before=response;response=demo.call('finish');demo.money_checks.append(check_finish(before,response,demo.protocol_metadata));result.update(status='closed',final_balance=response['balance'],final_state='closed',collect_event=len(demo.events)-1)
  demo.protocol_metadata.setdefault('unresolved',[]).append(dict(kind='optional_check_card',reason='Collect verified; card-gamble choices advertised in the winning round have not been exercised'))
 if result['status']!='closed':raise ValueError('V1 bonus/finish/choice state preserved; continuation requires review')
 demo.prev=response
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
