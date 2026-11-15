"""Limbo's four explicit quick multipliers, native cents and result.win/bet."""
import re,hashlib
from fractions import Fraction
def metadata(source):
 if not re.search(r'command:"spin",options:\{bet:this\.totalBet,player_multiplier:Math\.round\(100\*[A-Za-z_$][\w$]*\.A?\.?data\.playerMultiplier\)\}',source) and not re.search(r'command:"spin",options:\{bet:this\.totalBet,player_multiplier:Math\.round\(100\*[A-Za-z_$][\w$]*\.playerMultiplier\)\}',source):raise ValueError('Native Limbo request multiplier conversion not proved')
 if not re.search(r'\.result\.win-[A-Za-z_$][\w$]*\.result\.bet',source):raise ValueError('Native Limbo payout interpretation not proved')
 quick=re.findall(r'targetMultiplierQuickBets:"([\d., ]+)"',source)
 if len(set(quick))!=1:raise ValueError('Limbo quick controls ambiguous')
 values=[Fraction(v.strip())*100 for v in quick[0].split(',')]
 if any(v.denominator!=1 or v<=100 for v in values):raise ValueError('Invalid native Limbo quick threshold')
 return dict(limbo_thresholds=[int(v) for v in values],source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Official quick multiplier controls; spin.options.player_multiplier=Math.round(100*playerMultiplier); displayed native balance delta=result.win-result.bet',coverage_limit='Four explicit quick multiplier controls; arbitrary continuous/custom thresholds are not exhaustively enumerated.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];minimum=o['bet_limits']['min_bet']
 if c.get('code')!='FUN' or c.get('subunits')!=100 or type(minimum) is not int or minimum<=0 or type(initial.get('balance')) is not int or 'spin' not in initial.get('available_commands',[]):raise ValueError('Unverified Limbo FUN initial schema')
 return [dict(name='multiplier:'+str(Fraction(value,100)),protocol='legacy-limbo',command='spin',options={'bet':minimum,'player_multiplier':value},cost_native=minimum) for value in meta['limbo_thresholds']]
def settled(before,response,cost):
 result=response.get('result',{});win=result.get('win');bet=result.get('bet');balance=response.get('balance')
 if response.get('game',{}).get('state')!='closed' or any(type(v) is not int for v in [before,cost,win,bet,balance]) or win<0 or bet!=cost:raise ValueError('Unverified native Limbo result or open state')
 expected=before-cost+win
 if expected!=balance:raise ValueError('Limbo native balance mismatch')
 return dict(status='closed',final_balance=balance,final_state='closed',win_native=win,check=dict(kind='limbo_native_balance',expected=expected,actual=balance,cost_native=cost,win_native=win,ok=True))
def run(demo,mode,initial):
 old=demo.prev or initial
 if 'spin' not in old.get('available_commands',[]):raise ValueError('Limbo spin not currently available')
 if old['balance']<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 demo.active_mode=mode;start=len(demo.events);r=demo.call('spin',mode['options']);result=settled(old['balance'],r,mode['cost_native']);demo.money_checks.append(result.pop('check'));demo.prev=r
 return dict(mode=mode,first_event=start,last_event=len(demo.events)-1,**result)
