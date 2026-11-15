"""Resume already paid type-selecting bonus; add only still-unexercised source branches."""
import json,sys,time,copy,shutil
from run_demo_qa import ROOT,PRIVATE,save,now,modes_from_init,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore_rejected_continuation,adopt_observed_init
from legacy_metadata import prove_freespin_types
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid=sys.argv[1]
 if gid not in ['MonsterHunt','AlohaKingElvis','CatchTheGoldHoldAndWin']:raise ValueError('Unprepared type selection')
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore_rejected_continuation(gid,400,202,'unavailable_action','freespin',None);meta=prove_freespin_types(gid,d.opener);modes=modes_from_init(r['events'][0]['response'],meta);mode=modes[len(r['modes'])];trigger=len(r['events'])-2
 if r['events'][trigger]['request'].get('command')!='spin' or r['events'][trigger]['request'].get('options')!=mode['options'] or d.last_response.get('flow',{}).get('state')!='freespins':raise RuntimeError('Paid trigger differs from prepared branch')
 archive=ROOT/'live'/'attempts'/(gid+'.before-freespin-type-selection.json')
 if archive.exists():raise RuntimeError('Recovery previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-freespin-type-selection.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);current=adopt_observed_init(d,r,gid);d.active_mode=mode;d.protocol_metadata=meta;d.freespin_type_confirmed=False
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live'/(gid+'.json');r.update(status='running',declared_modes=modes,protocol_metadata=meta,events=d.events);r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  final=d.settle(current);d.prev=final;r['modes'].append(dict(mode=mode,status='closed',first_event=trigger,last_event=len(d.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True,choice_actions=getattr(d,'choice_actions',[])))
  for remaining in modes[len(r['modes']):]:
   r['modes'].append(d.run_mode(remaining,r['events'][0]['response']));r.update(events=d.events,checks=d.money_checks);save(path,r)
  r['status']=completion_status(r,meta)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
