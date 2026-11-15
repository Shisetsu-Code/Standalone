"""Offline classification of received final rounds with unexplained native balance changes."""
import json,copy
from fractions import Fraction
from run_demo_qa import ROOT,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 for gid in ['TheGodfather3PillarsOfPower','RocketEruptionTripleBlast']:
  path=ROOT/'live'/(gid+'.json');r=json.loads(path.read_text(encoding='utf8'))
  if r.get('reason')!='Native combined OGA round balance mismatch' or len(r['modes'])!=1 or r['events'][-1]['response']['result'].get('final') is not True:raise RuntimeError('Unreviewed closure '+gid)
  archive=ROOT/'live'/'attempts'/(gid+'.before-received-closure-classification.json')
  if archive.exists():raise RuntimeError('Already classified '+gid)
  save(archive,copy.deepcopy(r));start=r['modes'][0]['last_event']+1;mode=r['declared_modes'][1];before=r['events'][start-1]['response']['result']['balance'];balance=Fraction(str(before))-mode['cost_native'];win=Fraction(0);changes=[]
  for i,event in enumerate(r['events'][start:],start):
   result=event['response']['result'];value=result.get('resp',{}).get('win')
   if type(value) not in [int,float]:raise RuntimeError('Unverified native payout')
   win+=Fraction(str(value))
   if result.get('final') is not True:
    actual=Fraction(str(result['balance']))
    if actual!=balance:changes.append(dict(kind='native_nonfinal_balance_discontinuity',event=i,before_native=int(balance),after_native=result['balance'],delta_native=int(actual-balance),cause='unverified; possible FUN wallet renewal is a hypothesis, not a gameplay win'));balance=actual
  if not changes:raise RuntimeError('No observed nonfinal balance change')
  r.setdefault('provider_state_observations',[]).extend(changes);r['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(r['events'])-1,final_balance=r['events'][-1]['response']['result']['balance'],final_state='final',win_native=int(win) if win.denominator==1 else float(win),resumed_existing_purchase=True,monetary_status='unresolved_native_balance_discontinuity',unexpected_balance_change_native=sum(x['delta_native'] for x in changes)))
  r.update(status=completion_status(r,r['protocol_metadata']),reason='Received bonus final is recorded; original monetary checks still fail and remaining purchase is pending',reconciled_at=now());save(path,r);state['results'][gid].update(status=r['status'],modes_closed=2);print(gid,'received bonus closed; native balance change',changes[0]['delta_native'],'unresolved')
 state['updated_at']=now();save(ROOT/'run-state.json',state)
