"""Continue an already paid bonus only after matching non-wagering init and official command proof."""
import json,time,sys,copy
from run_demo_qa import ROOT,save,now,completion_status
from checkpoint_guard import acquire
from legacy_recovery import restore,adopt_observed_init
from legacy_metadata import prove_continuations
if __name__=='__main__':
 runner_lock_handle=acquire(ROOT/'runner.lock');gid=sys.argv[1];state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before restoring context')
 demo,report=restore(gid);proof=prove_continuations(gid,demo.opener);available=[a for a in demo.last_response['flow']['available_actions'] if a!='init']
 if len(available)!=1 or available[0] not in proof['legacy_continuations']:raise RuntimeError('Pending request fields not source-verified')
 mode=report['declared_modes'][len(report['modes'])];trigger=len(demo.events)-1
 if demo.events[-1]['request'].get('command')!='spin' or demo.events[-1]['request'].get('options')!=mode['options']:raise RuntimeError('Trigger/coverage requires separate review')
 archive=ROOT/'live'/'attempts'/(gid+'.before-known-continuation-recovery.json')
 if archive.exists():raise RuntimeError('Recovery previously attempted; do not repeat')
 save(archive,copy.deepcopy(report));current=adopt_observed_init(demo,report,gid);demo.protocol_metadata=report.get('protocol_metadata',{});demo.protocol_metadata.update(proof);demo.active_mode=mode
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state);path=ROOT/'live'/(gid+'.json');report.update(protocol_metadata=demo.protocol_metadata,status='running',events=demo.events);report.pop('reason',None);save(path,report)
 try:
  final=demo.settle(current);demo.prev=final;report['modes'].append(dict(mode=mode,status='closed',first_event=trigger,last_event=len(demo.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True))
  for mode in report['declared_modes'][len(report['modes']):]:report['modes'].append(demo.run_mode(mode,report['events'][0]['response']));report.update(events=demo.events,checks=demo.money_checks);save(path,report)
  report['status']=completion_status(report,demo.protocol_metadata)
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],flush=True)
