"""Guarded parent CLI for exact received Elements/Infinity source corrections."""
import json,time,copy,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status,modes_from_init
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import prove_native_modes_extra
from native_modes_extra import resume_remaining,resume_received,resume_received_spin
if __name__=='__main__':
 gid=sys.argv[1]
 if gid not in ['ElementsOfPower','InfinityPull']:raise ValueError('No reviewed recovery contract')
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause queue first')
 d,r=restore(gid);meta=prove_native_modes_extra(gid,d.opener);initial=r['events'][0]['response'];modes=modes_from_init(initial,meta)
 if meta['source_sha256']!=r['protocol_metadata']['source_sha256']:raise ValueError('Source version changed')
 received_active_spin='--received-active-spin' in sys.argv[2:]
 expected_count=1 if gid=='InfinityPull' or received_active_spin else 0
 logical_keys=['name','protocol','game_id','command','options','cost_native','target','source_sha256']
 if len(r['modes'])!=expected_count or len(r['declared_modes'])!=len(modes) or any(any(old.get(k)!=new.get(k) for k in logical_keys) for old,new in zip(r['declared_modes'],modes)):raise ValueError('Unexpected progressed modes; no replay')
 received_init_only='--received-init-only' in sys.argv[2:]
 if received_init_only and (gid!='ElementsOfPower' or r['events'][-1]['request'].get('command')!='init' or r.get('reason')!='Received Elements init changed pending cashout state'):raise ValueError('Not the exact received initialization correction')
 if received_active_spin and (gid!='ElementsOfPower' or r['events'][-1]['request'].get('command')!='spin' or r['events'][-1].get('status')!=200 or not r.get('reason','').startswith('Native wallet mismatch:')):raise ValueError('Not the exact active received spin correction')
 archive=ROOT/'live/attempts'/(gid+('.before-active-paid-spin-read.json' if received_active_spin else '.before-existing-init-finish.json' if received_init_only else '.before-received-native-settlement.json'))
 if archive.exists():raise ValueError('Recovery already reserved; inspect received state')
 save(archive,copy.deepcopy(r));shutil.copyfile(PRIVATE/(gid+'.session.json'),PRIVATE/'attempts'/(gid+'.before-received-native-settlement.session.json'))
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
 d.protocol_metadata=meta;d.prev=d.last_response;r.update(protocol_metadata=meta,declared_modes=modes,status='running');r.pop('reason',None);r.pop('error_type',None);path=ROOT/'live'/(gid+'.json')
 try:
  if gid=='ElementsOfPower':
   if received_active_spin:r['modes'].append(resume_received_spin(d,modes[1],initial))
   else:
    if not received_init_only:d.call('init')
    r['modes'].append(resume_received(d,modes[0],initial));r.update(events=d.events,checks=d.money_checks);save(path,r)
    for mode in modes[1:]:
     r['modes'].append(d.run_mode(mode,initial));r.update(events=d.events,checks=d.money_checks);save(path,r)
  else:
   for result in resume_remaining(d,modes[1:],initial):
    r['modes'].append(result);r.update(events=d.events,checks=d.money_checks);save(path,r)
  r['status']=completion_status(r,meta)
 except Exception as error:r.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now(),provider_state_observations=getattr(d,'provider_state_observations',[]));save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],state['results'][gid]['modes_closed'],r.get('reason',''))
