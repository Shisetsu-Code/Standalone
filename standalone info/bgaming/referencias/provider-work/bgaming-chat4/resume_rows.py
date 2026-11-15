"""Reconcile an already closed rows-mode response, then test only its still-unexecuted modes."""
import json,time,copy,sys
from run_demo_qa import ROOT,save,now,modes_from_init
from legacy_recovery import restore
from legacy_metadata import prove_default
from audit_live import audit
if __name__=='__main__':
 gid=sys.argv[1];state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before restoring context')
 demo,report=restore(gid)
 if report.get('reason')!='Wallet reconciliation mismatch; review required' or demo.last_response['flow']['state']!='closed':raise RuntimeError('Only the already closed rows-price audit case is supported')
 original=copy.deepcopy(report);save(ROOT/'live'/'attempts'/(gid+'.before-rows-audit-correction.json'),original)
 metadata=prove_default(gid,demo.opener);initial=report['events'][0]['response'];modes=modes_from_init(initial,metadata);i=len(report['modes']);event=report['events'][-1];mode=modes[i]
 if event['request'].get('command')!='spin' or event['request']['options']!=mode['options']:raise RuntimeError('Last request does not match source-derived pending mode')
 before=report['events'][-2]['response'];credit=before['balance']['game'] if before['flow']['state']=='closed' else 0;expected=before['balance']['wallet']+credit-mode['cost_native'];actual=demo.last_response['balance']['wallet']
 if expected!=actual:raise RuntimeError('Source-derived rows debit still differs; no continuation')
 candidate=copy.deepcopy(report);candidate['protocol_metadata']=metadata;independent=audit(candidate)
 if independent['failed']:raise RuntimeError('Independent historical audit failed; no continuation')
 report.setdefault('superseded_checks',[]).extend(dict(check=c,reason='Normal row factor omitted in original QA expectation; native request/response unchanged') for c in report.get('checks',[]) if not c.get('ok'))
 demo.money_checks=[c for c in report.get('checks',[]) if c.get('ok')];demo.money_checks.append(dict(kind='recovered_native_rows_debit',expected=expected,actual=actual,ok=True));report['protocol_metadata']=metadata;report['superseded_declared_modes']=report['declared_modes'];report['declared_modes']=modes
 report['modes'].append(dict(mode=mode,status='closed',first_event=len(demo.events)-1,last_event=len(demo.events)-1,final_balance=demo.last_response['balance'],final_state='closed',recovered_received_response=True));demo.prev=demo.last_response
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state);report['status']='running';report.pop('reason',None);path=ROOT/'live'/(gid+'.json');save(path,report)
 try:
  for mode in modes[len(report['modes']):]:
   report['modes'].append(demo.run_mode(mode,initial));report.update(events=demo.events,checks=demo.money_checks);save(path,report)
  report['status']='complete_declared_modes' if all(m['status']=='closed' for m in report['modes']) else 'partial'
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],flush=True)
