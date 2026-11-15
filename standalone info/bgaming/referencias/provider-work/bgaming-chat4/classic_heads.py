"""Classic Heads/Tails native flip command; original FUN amounts only."""
import re,hashlib
def metadata(source,gid):
 if gid not in ['HeadsTails','HeadsTailsXY'] or not re.search(r'\.games\.'+gid+r'=\{',source):raise ValueError('Classic coin game registration absent')
 if not re.search(r'command:"flip",options:\{side:[A-Za-z_$][\w$]*,bet:[A-Za-z_$][\w$]*\.Bet\.config\.line_bet\}',source) or not re.search(r'\.result\?[A-Za-z_$][\w$]*\.setBalance\(([A-Za-z_$][\w$]*)\.balance-\1\.result\):[A-Za-z_$][\w$]*\.setBalance\(\1\.balance\)',source):raise ValueError('Classic flip request/scalar result contract not proved')
 if 'M("head")' not in source or 'M("tail")' not in source:raise ValueError('Classic side callback literals absent')
 return dict(classic_heads_verified=True,protocol='classic-heads',source_sha256=hashlib.sha256(source.encode()).hexdigest(),source_game_id=gid,side_values=['head','tail'],evidence='Explicit shared classic game registration, UI side callbacks head/tail, flip options side/bet, response.result is scalar and absent/zero contributes no prize')
def plan(initial,meta):
 o=initial['options'];currency=o['currency'];bet=o.get('min_bet')
 if not meta.get('classic_heads_verified') or currency.get('code')!='FUN' or currency.get('subunits')!=100 or type(bet) is not int or bet<=0 or type(initial.get('balance')) is not int or 'flip' not in initial.get('available_commands',[]):raise ValueError('Unverified native coin initial state')
 return [dict(name='side:'+side,protocol='classic-heads',command='flip',options={'side':side,'bet':bet},cost_native=bet) for side in ['head','tail']]
def settled(before,response,cost):
 game=response.get('game',{});win=response.get('result',0);balance=response.get('balance')
 if game.get('state')!='closed' or game.get('flip_result') not in ['head','tail'] or any(type(v) is not int for v in [before,win,balance,cost]) or win<0:raise ValueError('Unverified native coin outcome/result')
 expected=before-cost+win
 if balance!=expected:raise ValueError('Classic coin native balance discrepancy')
 return dict(status='closed',final_state='closed',final_balance=balance,win_native=win,coin_result=game['flip_result'],check=dict(kind='classic_heads_native_balance',expected=expected,actual=balance,cost_native=cost,win_native=win,ok=True))
def run(demo,mode,initial):
 current=demo.prev or initial
 if 'flip' not in current.get('available_commands',[]):raise ValueError('Flip not currently advertised')
 if current['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);response=demo.call('flip',mode['options']);result=settled(current['balance'],response,mode['cost_native']);demo.money_checks.append(result.pop('check'));demo.prev=response
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
