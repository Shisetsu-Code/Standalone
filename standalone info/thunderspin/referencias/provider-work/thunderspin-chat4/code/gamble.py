"""One native gamble per enabled game, with at most three labelled preparations."""
import json,pathlib,msvcrt,hashlib
from campaign import ROOT,Campaign,save,clean,number
from contracts import gamble_action,next_action
from native import audit_packets
def finish_gamble(runner,cfg,fp,init,c,p,source):
 offer=c['journal'][-1]['response'];q=gamble_action(offer,source)
 if q is None or sum(number(x['response']['Balance']['TotalWinCents']) for x in c['journal'])<=0:raise ValueError('native_positive_gamble_offer_required')
 if init['response'].get('GameSettings',{}).get('IsGambleAllowed') is not True:raise ValueError('gamble_not_enabled')
 save(ROOT/'private/references'/cfg['slotcode']/'gamble-contract.json',{'source':cfg['source_client'],'sha256':hashlib.sha256(source.encode()).hexdigest(),'choice':'native red=0; one gamble only','scope':'prep parent is a distinct conditional-mode case, not repeated normal coverage'})
 c['mode']='GAMBLE';c['purpose']='conditional_gamble_with_labelled_parent';c['status']='gamble_sending';save(p,c)
 for endpoint,body in [('_Gamble',dict(q,sid=cfg['sid'])),('_AcceptWin',{'sid':cfg['sid']})]:
  if endpoint=='_AcceptWin' and c.get('status')=='verified':break
  packet={'endpoint':endpoint,'game':cfg['slotcode'],'session_fingerprint':fp,'request':clean(body),'status':'sending','http_status':None};c['journal'].append(packet);save(p,c)
  try:
   r,_=runner.request(cfg.get('service_base',cfg['host']+'/service')+'/'+endpoint,data=body,journal=ROOT/'private/journals'/cfg['slotcode']/('GAMBLE-'+endpoint+'.json'));packet.update(http_status=200,status='received',response=clean(r.json()));save(p,c);result=audit_packets([init]+c['journal'])
   if result['closed_rounds']:
    c['audit']=result['closed_rounds'][0];c['status']='verified';save(p,c);print(json.dumps({'game':cfg['slotcode'],'mode':'GAMBLE','status':'verified','is_win':c['audit']['gamble']['is_win'],'payout_cents':c['audit']['payout_cents']}),flush=True);break
   if endpoint=='_Gamble' and packet['response'].get('Gamble',{}).get('IsWin') is not True:raise ValueError('unknown_gamble_outcome_no_repeat')
  except Exception as exc:c.update(status='hold_do_not_repeat',error=str(exc));save(p,c);raise
 if c['status']!='verified':raise ValueError('gamble_not_closed')
def main():
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);runner=Campaign();runner.state['pass']='gamble'
 try:
  catalogue=json.loads((ROOT/'results/catalogue.json').read_text())
  for g in catalogue:
   plan_path=ROOT/'private/plans'/(g['slug']+'.json')
   if not plan_path.exists() or (ROOT/'private/holds'/(g['slug']+'.json')).exists():continue
   plan=json.loads(plan_path.read_text())
   if not any(m['mode']=='gamble' for m in plan.get('pending_modes',[])):continue
   existing=[json.loads(p.read_text()) for p in (ROOT/'private/rounds'/plan['game']).glob('GAMBLE_PREP_*.json')]
   if any(c.get('status')!='verified' for c in existing):raise ValueError('existing_gamble_preparation_no_retry')
   if any(c.get('mode')=='GAMBLE' for c in existing):continue
   if len(existing)>=3:continue
   source=(ROOT/'private/references'/g['slug']/'client.js').read_text(encoding='utf-8')
   if gamble_action({'NextMode':'root','FreeSpinsLeft':0,'waitForAcceptWin':True},source) is None:continue
   runner.state['current']={'slug':g['slug'],'stage':'fresh_demo_for_conditional_gamble'};runner.checkpoint();cfg,fp,init,init_path=runner.prepare(g);b=init['response']['Balance'];denom=min(b['CoinValue']);level=min(b['BetLevel']);cost=number(init['response'].get('DefaultBet',b['DefaultBet']))*number(denom)*number(level);lines=b.get('CurrentLinesCount',0)
   for i in range(len(existing)+1,4):
    mode='GAMBLE_PREP_'+str(i);runner.state['current']={'game':cfg['slotcode'],'mode':mode,'stage':'bounded_parent_preparation'};runner.checkpoint();before=init['response']['Balance']['ScoreCents'];next_init,lines=runner.run_case(cfg,fp,init,init_path,mode,str(cost),denom,level,lines,stop_at_gamble_offer=True);p=ROOT/'private/rounds'/cfg['slotcode']/(mode+'.json');c=json.loads(p.read_text())
    if c['status']=='gamble_offer_ready':
     bound=dict(init,response=dict(init['response'],Balance=dict(init['response']['Balance'],ScoreCents=before)));finish_gamble(runner,cfg,fp,bound,c,p,source);break
    init=next_init
   runner.state['completed_games'].append({'game':cfg['slotcode'],'bounded_preparations':i});runner.checkpoint()
  runner.state['status']='safe_passes_finished_pending_final_audit';runner.checkpoint()
 except Exception as exc:runner.state.update(status='stopped_for_review',error=str(exc));runner.checkpoint();print(json.dumps({k:runner.state.get(k) for k in ['pid','status','current','error']}),flush=True)
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
