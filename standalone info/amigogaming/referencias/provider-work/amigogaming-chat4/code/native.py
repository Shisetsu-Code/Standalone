"""Strict pure ledger using native money decimals and credit wins."""
from decimal import Decimal as D
def minimum_bet(i):
 candidates=[]
 for b in i['bets']:
  for d in i['denominations']:
   for m in i['multipliers']:
    value=D(str(b['value']))*D(d)*D(str(m))
    if value>0 and value<=D(i['maxBet']) and value>=D(str(i.get('minBet',0))):candidates.append((value,b['value'],m,d))
 _,b,m,d=min(candidates)
 return {'@type':'BetParams','bet':b,'multiplier':m,'denomination':d}
def resolved(a):
 states=a['states'];cur=states['current'];new=states.get('initialized')
 if new and states.get(new,{}).get('status')=='INIT':return new
 seen=set()
 while cur!='SLOT' and states.get(cur,{}).get('status')=='FINISHED':
  if cur in seen:raise ValueError('cyclic_parent')
  seen.add(cur);cur=states[cur].get('parentFeatureId','SLOT')
 return cur
def terminal(a):
 if resolved(a)!='SLOT':return False
 s=a['states'].get('SLOT',{})
 return s.get('status')=='FINISHED' and s.get('stepsAvailable',0)==0
def audit(init,packets,multiplier):
 if not packets:raise ValueError('empty_round')
 bet=packets[0]['request']['action']['betParams'];denom=D(bet['denomination']);base=denom*D(str(bet['bet']))*D(str(bet['multiplier']));cost=base*D(str(multiplier));before=D(init['balance']['amount']);last=packets[-1]['response'];currency=init['balance']['currency'];round_id=None
 for n,p in enumerate(packets):
  recovered=p.get('recovery_snapshot')
  if recovered:
   if p['status']!='sending' or not p.get('recovery_reference') or recovered.get('@type')!='responses.InitResponse' or not n:raise ValueError('invalid_recovery_witness')
   q=p['request']['action'];prev=packets[n-1].get('response') or packets[n-1].get('recovery_snapshot');cur=resolved(prev);choice=q.get('choice')
   if q.get('@type')!='features.pickme.action.PickMeAction' or not isinstance(choice,int) or prev['states'][cur]['choices'][choice]!=-1 or recovered['states'][cur]['choices'][choice]==-1:raise ValueError('choice_receipt_not_proven')
   a=recovered
  else:
   if p['status']!='received' or p['response'].get('@type')!='responses.ActionResponse':raise ValueError('uncertain_or_error_response')
   a=p['response']
   if a.get('id')!=p['request']['id']:raise ValueError('response_id_mismatch')
  if round_id is None:round_id=a['round']
  if a['round']!=round_id or round_id<=init['round']:raise ValueError('round_binding')
  if a['balance']['currency']!=currency:raise ValueError('currency_changed')
  if n and terminal(packets[n-1].get('response') or packets[n-1].get('recovery_snapshot')):raise ValueError('extra_paid_entry_after_terminal')
  if a.get('betParams')!=bet:raise ValueError('bet_params_changed')
 if not terminal(last):raise ValueError('round_not_closed')
 payout=D(str(last['win']))*denom;after=D(last['balance']['amount'])
 if after!=before-cost+payout:raise ValueError('ledger_not_reconciled')
 return {'round':round_id,'cost':str(cost),'payout':str(payout),'balance_before':str(before),'balance_after':str(after),'currency':currency,'requests':len(packets),'closed':True}
