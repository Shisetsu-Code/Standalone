"""Continue only after the already received Rocket finish is source-normalized offline."""
import json,time,copy,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status,modes_from_init
from legacy_recovery import restore
from legacy_metadata import prove_native_tables
from native_tables_extra import reconcile,dice_effective_balance,dice_pending_credit,dice_terminal
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 gid=sys.argv[1]
 if gid not in ['RocketDice','RocketDiceXY']:raise ValueError('Rocket game required')
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore(gid);archive=ROOT/'live/attempts'/(gid+'.before-deferred-prize-read.json');path=ROOT/'live'/(gid+'.json');meta=prove_native_tables(gid,d.opener);modes=modes_from_init(r['events'][0]['response'],meta)
 if archive.exists() or len(r['events'])!=3 or r['modes'] or r['events'][-1]['request'].get('command')!='finish' or r['events'][1]['request'].get('options')!=modes[0]['options'] or not dice_terminal(d.last_response) or meta['source_sha256']!=r['protocol_metadata']['source_sha256']:raise RuntimeError('Not the single already received source-matching finish; no replay')
 checked=reconcile(r['events'][-2]['response'],d.last_response,0,protocol='native-rocket-dice',command='finish');save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-deferred-prize-read.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);d.money_checks.append(checked);d.prev=d.last_response;d.protocol_metadata=meta
 r['modes'].append(dict(mode=modes[0],status='closed',first_event=1,last_event=2,final_balance=d.last_response['balance'],final_effective_balance_native=dice_effective_balance(d.last_response),final_pending_credit_native=dice_pending_credit(d.last_response),final_state=d.last_response['game']['state'],normalized_existing_received_finish=True));r.update(protocol_metadata=meta,declared_modes=modes,status='running');r.pop('reason',None);r.pop('error_type',None)
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);save(path,r)
 try:
  for mode in modes[1:]:
   r['modes'].append(d.run_mode(mode,r['events'][0]['response']));r.update(events=d.events,checks=d.money_checks);save(path,r)
  r['status']=completion_status(r,meta)
 except Exception as error:r.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
