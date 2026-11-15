"""Finish an existing fresh demo bonus and source-verified optional purchases; never repeats its trigger."""
import json,time,sys,copy
from run_demo_qa import ROOT,PRIVATE,save,now
from legacy_recovery import restore
from legacy_metadata import prove_default
if __name__=='__main__':
 gid=sys.argv[1];state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before restoring context')
 demo,report=restore(gid);metadata=prove_default(gid,demo.opener)
 if not metadata.get('extra_bonus_command_verified') or len(metadata['extra_bonus_types'])!=4:raise RuntimeError('Source does not prove all optional bonus request types')
 if demo.last_response['flow']['state']!='freespins' or 'buy_extra_bonus' not in demo.last_response['flow']['available_actions']:raise RuntimeError('No pending optional-purchase state')
 rb=json.loads((PRIVATE/'readback'/(gid+'.json')).read_text(encoding='utf8'));r=rb['response'];old=demo.last_response
 if rb['status']!=200 or rb['time']<=report['events'][-1]['time'] or r.get('flow',{}).get('round_id')!=old['flow']['round_id'] or r.get('flow',{}).get('state')!=old['flow']['state'] or r.get('features',{}).get('bonus_data')!=old['features']['bonus_data'] or r.get('options',{}).get('currency',{}).get('code')!='FUN':raise RuntimeError('Latest non-wagering init no longer matches pending FUN bonus')
 index=len(report['modes']);mode=report['declared_modes'][index]
 if report['events'][-1]['request'].get('command')!='spin' or report['events'][-1]['request']['options']!=mode['options']:raise RuntimeError('Trigger already progressed; separate recovery required')
 archive=ROOT/'live'/'attempts'/(gid+'.before-optional-bonus-recovery.json')
 if archive.exists():raise RuntimeError('Recovery archive already exists; no duplicate purchase')
 save(archive,copy.deepcopy(report));time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state)
 demo.protocol_metadata=metadata;demo.active_mode=mode;demo.active_extra_types=set();demo.offered_extra_types=set();demo.bonus_operations=[];start=len(demo.events)-1
 if r['balance']!=old['balance']:
  report.setdefault('provider_state_observations',[]).append(dict(kind='native_init_balance_refresh',before_native=old['balance'],after_native=r['balance'],event=len(demo.events),note='Observed provider response while retaining the same bonus round/state; not a gameplay win or a client-side balance edit'))
 demo.events.append(dict(time=rb['time'],request=demo.clean.clean(rb['request']),response=demo.clean.clean(r),status=rb['status'],response_sha256=rb['response_sha256'],kind='non_wagering_init_reconciliation'));old=r;demo.last_response=r
 report.update(protocol_metadata=metadata,status='running',events=demo.events);report.pop('reason',None);path=ROOT/'live'/(gid+'.json');save(path,report)
 try:
  final=demo.settle(old);demo.prev=final
  report['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(demo.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True,bonus_operations=[dict(op,bonus_round_closed=True) for op in demo.bonus_operations],extra_types_offered=sorted(demo.offered_extra_types),extra_types_tested=sorted(demo.active_extra_types)))
  covered=set(demo.active_extra_types);offered=set(demo.offered_extra_types)
  for mode in report['declared_modes'][len(report['modes']):]:
   result=demo.run_mode(mode,report['events'][0]['response']);report['modes'].append(result);covered.update(result.get('extra_types_tested',[]));offered.update(result.get('extra_types_offered',[]));report.update(events=demo.events,checks=demo.money_checks);save(path,report)
  pending=set(metadata['extra_bonus_types'])-covered;report['bonus_mode_coverage']=dict(source_types=metadata['extra_bonus_types'],offered=sorted(offered),tested=sorted(covered),pending=[dict(bonus_type=t,reason='Not exercised in the observed available bonus states') for t in sorted(pending)])
  report['status']='complete_declared_modes' if not pending and all(m['status']=='closed' for m in report['modes']) else 'partial'
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);print(gid,report['status'],'bonus purchases',len(demo.bonus_operations),'tested',sorted(demo.active_extra_types),flush=True)
