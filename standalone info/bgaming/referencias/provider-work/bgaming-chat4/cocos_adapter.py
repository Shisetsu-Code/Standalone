"""Cocos request/round semantics verified against the official Red and Hot Chilli client."""
import json
from fractions import Fraction

def plan(initial, metadata):
 r=initial['result'];attrs=r['currency_attributes']
 if r['currency']!='FUN' or attrs['code']!='FUN' or attrs['subunits']!=100 or attrs['exponent']!=2:raise ValueError('Unverified Cocos currency')
 if r.get('freebets') or r.get('state') is not None:raise ValueError('Existing Cocos state requires review')
 bet=min(r['config']['bet_limits']);modes=[]
 for product in [dict(name='normal',bid=0,purchased_feature=None,factor='1')]+metadata['products']:
  price=Fraction(bet)*Fraction(product['factor']);cost=(2*price.numerator+price.denominator)//(2*price.denominator)
  if cost<=0:raise ValueError('Invalid Cocos price')
  for policy in ['collect','gamble_once']:
   modes.append(dict(name=product['name']+('/gamble_once' if policy=='gamble_once' else ''),protocol='jsonrpc-cocos',bid=product['bid'],feature=product['purchased_feature'],bet_native=bet,cost_native=cost,policy=policy,conditional_gamble=policy=='gamble_once'))
 return modes

def continuation(result, metadata, policy, gambled, seen, stage):
 resp=result.get('resp',{});step=resp.get('step',{});expected=[str(x.get('esmid','')).upper() for x in step.get('er',[])]
 if any('RISK' in x for x in expected):
  values=metadata.get('gamble_req_values',{})
  decision='gamble' if policy=='gamble_once' and not gambled else 'collect'
  if decision not in values:raise RuntimeError('Unverified Cocos risk request')
  return {'custom_field':{'fid':{'a':values[decision]}}},gambled or decision=='gamble',seen,stage,decision
 if expected and all(x.startswith(('FS1_','FS2_')) for x in expected) and metadata.get('board_symbols',{}).get('Empty') is not None:
  layout=step['ff'][0]['f'] if step.get('ff') and step['ff'][0].get('f') else step.get('f');signature=(tuple(expected),json.dumps(layout,sort_keys=True))
  if stage!=signature:seen=set();stage=signature
  fid=step.get('fid',{})
  if isinstance(fid,dict) and 'x' in fid and 'y' in fid:seen.add((fid['x'],fid['y']))
  cd=step.get('cd',{})
  if isinstance(cd,str):cd=json.loads(cd)
  for cell in cd.get('fe',[]):
   if 'x' in cell and 'y' in cell:seen.add((cell['x'],cell['y']))
  candidates=[(x,y) for x,col in enumerate(layout or []) for y,cell in enumerate(col) if cell.get('e')==metadata['board_symbols']['Empty'] and (x,y) not in seen]
  if not candidates:raise RuntimeError('No verified Cocos hidden cell; state retained')
  x,y=candidates[0];seen.add((x,y))
  return dict(bid=resp['round']['bet']['id'],custom_field={'fid':{'x':x,'y':y}}),gambled,seen,stage,None
 raise RuntimeError('Unrecognized Cocos continuation; no input submitted')

def run(h,mode):
 from cocos_audit import get_win,money
 key=mode['bid']
 if mode.get('conditional_gamble') and key not in h.offers:return dict(mode=mode,status='not_applicable',reason='Risk not offered in preceding round',network_calls=0)
 if h.last.get('final') is False or (h.last.get('state') is not None and 'final' not in h.last):raise RuntimeError('Open Cocos round; no new purchase')
 before=h.last['balance'];cost=mode['cost_native'];bet=mode['bet_native'];start=len(h.parent.events)
 if money(before)<cost:return dict(mode=mode,status='insufficient_demo_balance')
 req=dict(bet=bet,bet_type='bet',bid=key)
 if mode['feature']:req['purchased_feature']=mode['feature']
 r=h.request('play',req)['result'];seen=set();stage=None;gambled=False;choices=[];offered=False
 for _ in range(500):
  if r.get('final') is True:break
  extra,gambled,seen,stage,decision=continuation(r,h.metadata,mode['policy'],gambled,seen,stage)
  if decision:choices.append(decision);h.offers.add(key);offered=True
  req=dict(bet=bet,bet_type='bet');req.update(extra);r=h.request('play',req)['result']
 else:raise RuntimeError('Cocos continuation limit; round retained')
 win=get_win(r.get('resp',{}));expected=money(before)-cost+win;actual=r['balance'];ok=expected==money(actual)
 h.parent.money_checks.append(dict(kind='round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=actual,ok=ok))
 if not ok:raise RuntimeError('Cocos wallet mismatch; inspect native evidence')
 return dict(mode=mode,status='branch_not_observed' if mode.get('conditional_gamble') and not gambled else 'closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=actual,final_state='final',win_ratio=[win.numerator,win.denominator],win_native=int(win) if win.denominator==1 else float(win),choices_taken=choices,risk_offered=offered)
