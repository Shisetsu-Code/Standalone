"""Independent exact-value audit and canonical report for observed Hyperhive JSON-RPC."""
import json,copy,hashlib
from fractions import Fraction
from pathlib import Path
from run_demo_qa import ROOT,PRIVATE,save,now
from analyze import Sanitizer
FACTORS={None:'1','freespin_chance':'1.4','freespin_buy':'100','high_freespin_buy':'200'}
def audit_rpc(initial,events,factors=FACTORS,variants=None):
 balance=initial['result']['balance'];checks=[];rounds=[];current=None
 for i,event in enumerate(events):
  q=event['request'];response=event['response']
  if 'result' not in response:checks.append(dict(event=i,kind='rpc_result',ok=False));continue
  r=response['result'];g=r.get('resp',{}).get('engine',{}).get('gamestate',{});req=q['params']['req'];cost=Fraction(0)
  if current is None:
   feature=req.get('purchased_feature');factor=factors.get(feature);matching=[v for v in (variants or []) if v['feature']==feature and all(req.get('custom_req',{}).get(k)==value for k,value in v['custom_params'].items())]
   if matching:
    if len(matching)!=1:raise ValueError('Ambiguous native variant')
    factor=matching[0]['factor']
   if factor is None:raise ValueError('Unmapped native feature cost')
   cost=Fraction(str(req['bet']))*Fraction(str(factor));assert cost.denominator==1
   current=dict(feature=feature,start_event=i,before_balance_native=balance,cost_native=int(cost),win_native=0,choices_taken=[],choices_offered=[],closed=False)
   rounds.append(current)
   if 'totalStake' in g:checks.append(dict(event=i,kind='initial_stake',expected=int(cost),actual=g['totalStake'],ok=Fraction(str(g['totalStake']))==cost))
  choice=req.get('custom_req',{}).get('choice')
  if choice is not None:current['choices_taken'].append(choice)
  offered=g.get('triggeringDetails',{}).get('nextAction')
  if isinstance(offered,list):current['choices_offered']=sorted(set(current['choices_offered'])|set(offered))
  win=r.get('resp',{}).get('win')
  if not isinstance(win,(int,float)):checks.append(dict(event=i,kind='native_win',ok=False));continue
  current['win_native']+=win
  expected=Fraction(str(current['before_balance_native']))-current['cost_native']
  if r.get('final') is True:expected+=Fraction(str(current['win_native']))
  actual=r['balance'];checks.append(dict(event=i,kind='wallet',expected_ratio=[expected.numerator,expected.denominator],actual_native=actual,cost_native=int(cost),win_native=win,credit_timing='round_final',ok=expected==Fraction(str(actual))))
  balance=actual;current['end_event']=i;current['final_balance_native']=actual
  if r.get('final') is True:
   expected=Fraction(str(current['before_balance_native']))-current['cost_native']+Fraction(str(current['win_native']));checks.append(dict(event=i,kind='round_balance',ok=expected==Fraction(str(actual))))
   current['closed']=True;current=None
 return checks,rounds
if __name__=='__main__':
 public=json.loads((ROOT/'transport/HotRocketMegaPotz.rpc-evidence.json').read_text(encoding='utf8'));checks,rounds=audit_rpc(public['initial'],public['events']);modes=[]
 for r in rounds:
  feature=r['feature'];suffix='/gamble_once' if 2 in r['choices_taken'] else '/collect' if 1 in r['choices_taken'] else '/no_choice' if feature in ('freespin_buy','high_freespin_buy') else ''
  name=(feature or 'normal')+suffix
  modes.append(dict(mode=dict(name=name,protocol='jsonrpc',purchased_feature=feature,cost_native=r['cost_native']),status='closed' if r['closed'] else 'open',first_event=r['start_event']+1,last_event=r.get('end_event',r['start_event'])+1,final_balance=r.get('final_balance_native'),win_native=r['win_native'],choices_taken=r['choices_taken'],choices_offered=r['choices_offered']))
 missing=[]
 for feature in FACTORS:
  relevant=[r for r in rounds if r['feature']==feature and r['closed']]
  if not relevant:missing.append(dict(feature=feature or 'normal',reason='no_closed_round'));continue
  offered={a for r in relevant for a in r['choices_offered']};taken={a for r in relevant for a in r['choices_taken']}
  for name,choice in [('collect',1),('gamble',2)]:
   if name in offered and choice not in taken:missing.append(dict(feature=feature,reason='choice_not_covered',choice=name))
 status='running' if any(not r['closed'] for r in rounds) else 'complete_declared_modes' if not missing and all(x['ok'] for x in checks) else 'partial'
 capture=json.loads((PRIVATE/'browser/HotRocketMegaPotz/capture.json').read_text(encoding='utf8'));clean=Sanitizer()
 init_record=next(e for e in capture['records'] if e.get('kind')=='http' and e.get('requestBody') and 'application/json' in e.get('contentType','') and json.loads(e['requestBody']).get('method')=='init');q=json.loads(init_record['requestBody']);q['id']='rpc-init-1'
 initial_event=dict(time=init_record['time'],request=clean.clean(q),response=public['initial'],status=init_record['status'],response_sha256=hashlib.sha256(init_record['body'].encode()).hexdigest())
 game=next(x for x in json.loads((ROOT/'catalog-live.json').read_text(encoding='utf8'))['games'] if x['game_id']=='HotRocketMegaPotz')
 report=dict(game=game,protocol='jsonrpc',status=status,initial=public['initial'],feature_cost_factors={str(k):v for k,v in FACTORS.items()},modes=modes,events=[initial_event]+public['events'],checks=checks,rounds=rounds,pending=missing,updated_at=now(),bootstrap=dict(client_version='0.0.54',math_versions=sorted({e['response']['result']['resp']['v'] for e in public['events'] if 'result' in e['response']}),currency=public['initial']['result']['currency_attributes']))
 save(ROOT/'live/HotRocketMegaPotz.json',report)
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));state['results']['HotRocketMegaPotz']=dict(status=status,modes_closed=sum(x['status']=='closed' for x in modes),report='live/HotRocketMegaPotz.json');state['active_game']='HotRocketMegaPotz' if status=='running' else None;state['updated_at']=now();save(ROOT/'run-state.json',state)
 print(status,'closed rounds',sum(r['closed'] for r in rounds),'checks',len(checks),'failed',sum(not x['ok'] for x in checks),'pending',missing)
