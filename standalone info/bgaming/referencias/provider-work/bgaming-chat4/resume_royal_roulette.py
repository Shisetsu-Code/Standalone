"""Normalize the received first Royal roulette result, then test only unexecuted types."""
import json,time,copy,shutil
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from legacy_recovery import restore
from royal_roulette import settled
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 gid='RoyalRoulette500X';d,r=restore(gid);modes=r['declared_modes'];archive=ROOT/'live/attempts/RoyalRoulette500X.before-native-float-read.json'
 if archive.exists() or r['modes'] or len(r['events'])!=2 or r['events'][-1]['request'].get('options')!=modes[0]['options']:raise RuntimeError('Not the single received first type; no retry')
 result=settled(r['events'][0]['response']['balance'],d.last_response,modes[0]['cost_native']);save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts/RoyalRoulette500X.before-native-float-read.session.json';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);d.money_checks.append(result.pop('check'));r['modes'].append(dict(mode=modes[0],first_event=1,last_event=1,normalized_existing_received_response=True,**result));d.prev=d.last_response
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live'/(gid+'.json');r.update(status='running');r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  for mode in modes[1:]:
   r['modes'].append(d.run_mode(mode,r['events'][0]['response']));r.update(events=d.events,checks=d.money_checks,provider_state_observations=getattr(d,'provider_state_observations',[]));save(path,r)
  r['status']=completion_status(r,r['protocol_metadata'])
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,provider_state_observations=getattr(d,'provider_state_observations',[]),finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
