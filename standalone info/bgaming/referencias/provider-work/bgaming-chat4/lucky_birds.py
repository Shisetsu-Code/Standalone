"""Lucky Birds source-proved start/step/bird/cashout protocol; one step per literal bird."""
import re,hashlib
from fractions import Fraction
def metadata(source):
 birds=list(dict.fromkeys(re.findall(r'\.birdColor="([a-z]+)"',source)))
 if set(birds)!={'red','orange','blue'} or not all(token in source for token in ['action:"start"','action:"step",bird:','action:"cashout"','.resp.win']):raise ValueError('Lucky Birds literal choices or lifecycle not proved')
 return dict(engine='lucky-birds',birds=birds,source_sha256=hashlib.sha256(source.encode()).hexdigest(),unresolved=[],evidence='Official API emits start, step with literal red/orange/blue bird and cashout, carrying native bet and state_lock. UI takes cashout payout from resp.win; crash/auto_loss has zero payout.',coverage_limit='Each of three birds tested for one step, then cashout when available. Unlimited repeated steps and rare maximum-win outcomes are not exhaustively generated. Platform-wide purchased_features allowlist does not imply purchases in this client.')
def plan(initial,meta):
 r=initial['result'];attrs=r['currency_attributes'];minimum=min(r['config']['bet_limits'])
 if r['currency']!='FUN' or attrs['subunits']!=100 or r.get('state') is not None or r.get('freebets') or type(minimum) is not int or minimum<=0:raise ValueError('Unverified Lucky Birds initial FUN state')
 return [dict(name='bird:'+bird,protocol='jsonrpc',bird=bird,bet_native=minimum,cost_native=minimum) for bird in meta['birds']]
def closed_result(before,bet,response):
 resp=response.get('resp',{});win=resp.get('win')
 if win is None and resp.get('result') in ['crash','auto_loss']:win=0
 if response.get('final') is not True or any(type(x) not in [int,float] for x in [before,bet,win,response.get('balance')]) or win<0:raise ValueError('Lucky Birds terminal/win schema unverified')
 expected=Fraction(str(before))-Fraction(str(bet))+Fraction(str(win));actual=Fraction(str(response['balance']))
 if expected!=actual:raise ValueError('Lucky Birds native round balance mismatch')
 return dict(kind='lucky_birds_round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=response['balance'],cost_native=bet,win_native=win,ok=True)
def run(h,mode):
 if h.last.get('final') is False or h.last.get('state') is not None and 'final' not in h.last:raise RuntimeError('Lucky Birds already has an open round')
 bet=mode['bet_native'];before=h.last['balance'];start=len(h.parent.events)
 if before<bet:return dict(mode=mode,status='insufficient_demo_balance')
 r=h.request('play',{'bet':bet,'action':'start'})['result']
 if r.get('final') is not False or Fraction(str(r['balance']))!=Fraction(str(before))-bet:raise RuntimeError('Lucky Birds start state/debit changed; no step sent')
 r=h.request('play',{'bet':bet,'action':'step','bird':mode['bird']})['result'];actions=['start','step']
 if r.get('final') is False:
  if r.get('resp',{}).get('result')!='survived' or Fraction(str(r['balance']))!=Fraction(str(before))-bet:raise RuntimeError('Unknown Lucky Birds nonfinal step; no cashout sent')
  r=h.request('play',{'bet':bet,'action':'cashout'})['result'];actions.append('cashout')
 check=closed_result(before,bet,r);h.parent.money_checks.append(check)
 return dict(mode=mode,status='closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=r['balance'],final_state='final',win_native=check['win_native'],actions=actions,result=r.get('resp',{}).get('result'))
def audit(initial,events):
 previous=initial['result'];current=None;checks=[];rounds=[]
 for i,event in enumerate(events):
  if event['request'].get('method')!='play':continue
  q=event['request']['params']['req'];r=event['response'].get('result')
  if r is None:checks.append(dict(event=i,kind='rpc_result',ok=False));continue
  if q['action']=='start':
   if current is not None:raise ValueError('New bird round before final')
   current=dict(before=previous['balance'],bet=q['bet'],first_event=i);rounds.append(current);checks.append(dict(event=i,kind='lucky_birds_start_debit',ok=Fraction(str(r['balance']))==Fraction(str(current['before']))-current['bet']))
  elif current is None:raise ValueError('Bird continuation without start')
  elif q['action'] not in ['step','cashout']:raise ValueError('Unknown bird request action')
  if r.get('final') is True:checks.append(dict(event=i,**closed_result(current['before'],current['bet'],r)));current.update(closed=True,last_event=i);current=None
  elif q['action']=='step':checks.append(dict(event=i,kind='lucky_birds_step_debit',ok=Fraction(str(r['balance']))==Fraction(str(current['before']))-current['bet']))
  previous=r
 return checks,rounds
