"""Cocos round-level audit: premiums use bid price; round.win is credited only at final."""
import json
from fractions import Fraction
from pathlib import Path
from run_demo_qa import ROOT,save,now

def money(value):
 if isinstance(value,bool):raise ValueError('Boolean in monetary field')
 return Fraction(str(value))
def get_win(resp):
 value=resp.get('round',{}).get('win') or resp.get('step',{}).get('win') or '0'
 return money(value)
def audit(initial,events,metadata):
 balance=initial['result']['balance'];prices={0:Fraction(1),**{p['bid']:Fraction(p['factor']) for p in metadata['products']}};checks=[];rounds=[];current=None
 for i,event in enumerate(events):
  q=event['request'];r=event.get('response',{}).get('result')
  if q.get('method')!='play':continue
  if r is None:checks.append(dict(event=i,kind='rpc_result',ok=False));continue
  req=q['params']['req'];resp=r.get('resp',{});round_data=resp.get('round',{});step=resp.get('step',{})
  if current is None:
   bid=req.get('bid',0);cost=money(req['bet'])*prices[bid];cost=Fraction((2*cost.numerator+cost.denominator)//(2*cost.denominator));current=dict(bid=bid,round_id=round_data.get('id'),start_event=i,before_balance_native=balance,cost_native=int(cost),base_bet_native=req['bet'],choices=[],picks=[],closed=False);rounds.append(current)
   if round_data.get('bet',{}).get('tb') is not None:checks.append(dict(event=i,kind='base_stake',expected=req['bet'],actual=round_data['bet']['tb'],ok=money(round_data['bet']['tb'])==money(req['bet'])))
  fid=req.get('custom_field',{}).get('fid',{})
  if 'a' in fid:current['choices'].append(fid['a'])
  if 'x' in fid and 'y' in fid:current['picks'].append(dict(x=fid['x'],y=fid['y']))
  expected=money(current['before_balance_native'])-current['cost_native']
  if r.get('final') is True:expected+=get_win(resp)
  actual=r['balance'];checks.append(dict(event=i,kind='wallet',expected_ratio=[expected.numerator,expected.denominator],actual_native=actual,ok=expected==money(actual),credit_timing='round_final'))
  balance=actual;current['end_event']=i;current['final_balance_native']=actual
  if r.get('final') is True:
   win=get_win(resp);current['win_native']=int(win) if win.denominator==1 else float(win);current['win_ratio']=[win.numerator,win.denominator];current['closed']=True;current=None
 return checks,rounds
if __name__=='__main__':
 gid='RedAndHotChilli';public=json.loads((ROOT/'transport'/(gid+'.cocos-evidence.json')).read_text(encoding='utf8'));checks,rounds=audit(public['initial'],public['events'],public['metadata']);products={0:'normal',**{p['bid']:p['name'] for p in public['metadata']['products']}};modes=[]
 for r in rounds:
  suffix='/gamble_once' if 'yes' in r['choices'] else '/collect' if 'no' in r['choices'] else ''
  modes.append(dict(mode=dict(name=products[r['bid']]+suffix,protocol='jsonrpc-cocos',bid=r['bid'],bet_native=r['base_bet_native'],cost_native=r['cost_native']),status='closed' if r['closed'] else 'open',first_event=r['start_event'],last_event=r.get('end_event'),final_balance=r.get('final_balance_native'),final_state='final' if r['closed'] else 'open',win_native=r.get('win_native'),choices_taken=r['choices'],cell_picks=r['picks']))
 covered={r['bid'] for r in rounds if r['closed']};missing=[]
 for bid in [0,1,2,3]:
  if bid not in covered:missing.append(dict(bid=bid,reason='no closed round'))
 for bid in [2,3]:
  choices={c for r in rounds if r['bid']==bid and r['closed'] for c in r['choices']}
  for choice in ['yes','no']:
   if choice not in choices:missing.append(dict(bid=bid,reason='choice not covered',choice=choice))
 status='running' if any(not r['closed'] for r in rounds) else 'complete_declared_modes' if not missing and all(x['ok'] for x in checks) else 'partial';game=next(x for x in json.loads((ROOT/'catalog-live.json').read_text(encoding='utf8'))['games'] if x['game_id']==gid)
 report=dict(game=game,protocol='jsonrpc-cocos',status=status,initial=public['initial'],protocol_metadata=public['metadata'],modes=modes,events=public['events'],checks=checks,rounds=rounds,pending=missing,updated_at=now());save(ROOT/'live'/(gid+'.json'),report)
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));state['results'][gid]=dict(status=status,modes_closed=sum(x['status']=='closed' for x in modes),report='live/'+gid+'.json');state['active_game']=gid if status=='running' else None;state['updated_at']=now();save(ROOT/'run-state.json',state)
 print(status,'closed rounds',sum(r['closed'] for r in rounds),'checks',len(checks),'failed',sum(not x['ok'] for x in checks),'pending',missing)
