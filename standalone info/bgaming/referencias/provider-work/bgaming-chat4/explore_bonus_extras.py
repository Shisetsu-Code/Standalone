"""Exercise missing source-known optional bonus purchases, prioritizing one branch per new FUN round."""
import json,time,copy,sys
from run_demo_qa import ROOT,save,now
from legacy_recovery import restore
if __name__=='__main__':
 gid=sys.argv[1];state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before branch exploration')
 demo,report=restore(gid);meta=report['protocol_metadata'];coverage=report['bonus_mode_coverage']
 if not meta.get('extra_bonus_command_verified') or demo.last_response['flow']['state']!='closed':raise RuntimeError('Source/round state not ready')
 covered=set(coverage['tested']);offered=set(coverage['offered']);known=set(meta['extra_bonus_types']);missing=known-covered
 if not missing:raise RuntimeError('No missing optional branch; no duplicate round')
 template=next(m['mode'] for m in report['modes'] if m['mode']['options'].get('purchased_feature')=='freespin_buy' and m['status']=='closed')
 archive=ROOT/'live'/'attempts'/(gid+'.before-extra-branch-exploration.json')
 if archive.exists():raise RuntimeError('Branch run already attempted; inspect evidence before repeating')
 save(archive,copy.deepcopy(report));time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state);demo.protocol_metadata=meta;demo.prev=demo.last_response;report['status']='running';path=ROOT/'live'/(gid+'.json');save(path,report)
 try:
  for attempt in range(8):
   missing=known-covered
   if not missing:break
   target=next(n for n in ['regenerate_bonus','extra_multiplier','extra_board','extra_spin'] if n in missing);priority=[target]+[n for n in ['regenerate_bonus','extra_multiplier','extra_board','extra_spin'] if n!=target]
   mode=copy.deepcopy(template);mode.update(name=template['name']+'/extra-first:'+target+'/attempt:'+str(attempt+1),extra_priority=priority,extra_target=target);report['declared_modes'].append(mode)
   result=demo.run_mode(mode,report['events'][0]['response']);report['modes'].append(result);covered.update(result.get('extra_types_tested',[]));offered.update(result.get('extra_types_offered',[]));report.update(events=demo.events,checks=demo.money_checks);save(path,report);print(gid,'branch attempt',attempt+1,'tested',result.get('extra_types_tested',[]),flush=True)
   if result['status']!='closed':break
  missing=known-covered;report['bonus_mode_coverage']=dict(source_types=meta['extra_bonus_types'],offered=sorted(offered),tested=sorted(covered),pending=[dict(bonus_type=t,reason='Not exercised after bounded source-verified available-state exploration') for t in sorted(missing)]);report['status']='complete_declared_modes' if not missing and all(m['status']=='closed' for m in report['modes']) else 'partial'
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);print(gid,report['status'],'covered',sorted(covered),flush=True)
