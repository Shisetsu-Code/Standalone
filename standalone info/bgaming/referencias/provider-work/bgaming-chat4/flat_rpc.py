"""Sweet Samurai native flat resp.win protocol, distinct from Cocos feature RequestBuilder."""
import re,hashlib
from fractions import Fraction
def metadata(source):
 if not re.search(r'body:\{req:\{bet:[A-Za-z_$][\w$]*,bet_type:[A-Za-z_$][\w$]*\},state_lock:this\.stateLock\},playMethod:"play"',source) or '.resp.win' not in source or 'purchased_feature' in source:raise ValueError('Flat native RPC request/payout or no-purchase contract not proved')
 return dict(engine='flat-rpc',source_sha256=hashlib.sha256(source.encode()).hexdigest(),unresolved=[],evidence='Official Sweet Samurai gateway play body req={bet,bet_type}, state_lock, and per-response resp.win used by WinModel. No purchased_feature request exists in this client.',coverage_limit='Normal native round and source-automatic continuations; platform purchased_features allowlist is not counted as visible purchases.')
def plan(initial,meta):
 r=initial['result'];bet=min(r['config']['bet_limits'])
 if r['currency']!='FUN' or r['currency_attributes']['subunits']!=100 or r.get('freebets') or r.get('state') is not None or type(bet) is not int or bet<=0:raise ValueError('Unverified flat RPC FUN schema')
 return [dict(name='normal',protocol='jsonrpc',bet_native=bet,cost_native=bet)]
def run(h,mode):
 if h.last.get('final') is False or h.last.get('state') is not None and 'final' not in h.last:raise RuntimeError('Flat round already open')
 before=Fraction(str(h.last['balance']));bet=mode['bet_native'];start=len(h.parent.events);total=Fraction(0)
 if before<mode['cost_native']:return dict(mode=mode,status='insufficient_demo_balance')
 for step in range(500):
  r=h.request('play',{'bet':bet,'bet_type':'bet'})['result'];resp=r.get('resp',{});win=resp.get('win')
  if type(win) not in [int,float] or win<0 or type(r.get('final')) is not bool or any(resp.get(k) for k in ['choices','gamble','next_action']):raise RuntimeError('Flat response requires unknown choice/schema; no retry')
  total+=Fraction(str(win))
  if r['final']:break
 else:raise RuntimeError('Flat RPC continuation bound reached')
 expected=before-mode['cost_native']+total;ok=expected==Fraction(str(r['balance']));h.parent.money_checks.append(dict(kind='flat_rpc_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=r['balance'],ok=ok))
 if not ok:raise RuntimeError('Flat RPC native balance mismatch')
 return dict(mode=mode,status='closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=r['balance'],final_state='final',win_native=int(total) if total.denominator==1 else float(total))
def audit(initial,events):
 balance=Fraction(str(initial['result']['balance']));current=None;checks=[];rounds=[]
 for index,event in enumerate(events):
  if event['request'].get('method')!='play':continue
  r=event['response'].get('result')
  if r is None:checks.append(dict(event=index,kind='rpc_result',ok=False));continue
  if current is None:current=dict(first_event=index,before=balance,cost=event['request']['params']['req']['bet'],total=Fraction(0))
  win=r.get('resp',{}).get('win')
  if type(win) not in [int,float]:raise ValueError('Flat native payout missing')
  current['total']+=Fraction(str(win))
  if r.get('final') is True:
   expected=current['before']-current['cost']+current['total'];actual=Fraction(str(r['balance']));checks.append(dict(event=index,kind='flat_rpc_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=r['balance'],ok=expected==actual));rounds.append(dict(first_event=current['first_event'],last_event=index,closed=True,cost_native=current['cost'],win_ratio=[current['total'].numerator,current['total'].denominator]));balance=actual;current=None
 return checks,rounds
