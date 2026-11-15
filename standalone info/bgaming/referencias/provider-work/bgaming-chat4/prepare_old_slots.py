"""Archive init-only V1 cases for corrected fresh QA; reconcile Book's received spin offline."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import prove_old_slot
from old_slots import plan,closed_result
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 gid='BookOfCats';demo,r=restore(gid);meta=prove_old_slot(gid,demo.opener);mode=plan(r['events'][0]['response'],meta)[0]
 if len(r['events'])!=2 or r['events'][1]['request']['options']!=mode['options']:raise RuntimeError('Book probe differs; no duplicate spin')
 if not r['modes']:
  archive=ROOT/'live'/'attempts'/(gid+'.before-offline-v1-conciliation.json')
  if archive.exists():raise RuntimeError('Already reconciled')
  save(archive,r);result=closed_result(r['events'][0]['response'],r['events'][1]['response'],mode,meta);check=result.pop('check');r['modes']=[dict(mode=mode,first_event=1,last_event=1,**result)];r['checks']=[check]
  meta['unresolved']=[dict(kind='buy_feature_value',native_multiplier=97,reason='Source advertises purchase; not exercised in this normal-only probe')]
  r.update(protocol_metadata=meta,reason='Received normal spin reconciled offline; advertised purchase remains pending',status=completion_status(r,meta),reconciled_at=now());save(ROOT/'live'/(gid+'.json'),r);state['results'][gid].update(status=r['status'],modes_closed=1)
 changed=[]
 for gid,result in list(state['results'].items()):
  path=ROOT/result['report'];r=json.loads(path.read_text(encoding='utf8'));events=r.get('events',[])
  if len(events)!=1 or events[0].get('request',{}).get('command')!='init':continue
  initial=events[0].get('response',{});options=initial.get('options',{})
  if type(initial.get('balance')) is not int or not options.get('line_bets') or 'spin' not in initial.get('available_commands',[]):continue
  # Static source fetch may fail; preserve that case and do not enqueue unproved wire.
  try:
   demo,_=restore(gid);meta=prove_old_slot(gid,demo.opener);plan(initial,meta)
   if not meta.get('v1_result_total_verified'):raise ValueError('V1 result default unproved')
  except Exception as e:print(gid,'not prepared',type(e).__name__);continue
  archive=ROOT/'live'/'attempts'/(gid+'.before-v1-lines-adapter.json')
  if archive.exists():raise RuntimeError('Already enqueued '+gid)
  save(archive,r);private=PRIVATE/(gid+'.session.json');target=PRIVATE/'attempts'/(gid+'.before-v1-lines-adapter.session.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,target)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason='Init only. Source-verified native V1 line dictionary adapter and closed result checks; new independent FUN QA context.'))
  del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(ROOT/'run-state.json',state);save(ROOT/'old-slots-requeue.json',dict(updated_at=now(),games=changed,book_normal_received_reconciled=True));print('V1 init-only cases enqueued',changed)
