"""Retain closed normal and exact rejected request; run only two source UI activators."""
import json,time,copy,shutil
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore_rejected_continuation
from legacy_metadata import load_client
from lucky_dragon_controls import metadata,plan
if __name__=='__main__':
 gid='LuckyDragonMultiDiceX';lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise ValueError('Pause first')
 d,r=restore_rejected_continuation(gid,422,203,'invalid_options','spin',dict(bet=10,purchased_feature='bonus_buy',purchased_feature_level='bonus_buy_0'))
 info,source=load_client(gid,d.opener);info.update(metadata(source));modes=plan(r['events'][0]['response'],info);archive=ROOT/'live/attempts'/(gid+'.before-literal-ui-controls.json')
 if archive.exists() or len(r['modes'])!=1 or r['modes'][0]['status']!='closed' or r['modes'][0]['mode']!=modes[0] or d.last_response['flow']['state']!='closed':raise ValueError('Original closed normal/rejection differs; no repeat')
 save(archive,copy.deepcopy(r));shutil.copyfile(PRIVATE/(gid+'.session.json'),PRIVATE/'attempts'/(gid+'.before-literal-ui-controls.session.json'))
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
 d.protocol_metadata=info;d.prev=d.last_response;r.update(protocol_metadata=info,declared_modes=modes,status='running');r.pop('reason',None);r.pop('error_type',None)
 try:
  for mode in modes[1:]:
   r['modes'].append(d.run_mode(mode,r['events'][0]['response']));r.update(events=d.events,checks=d.money_checks);save(ROOT/'live'/(gid+'.json'),r)
  r['status']=completion_status(r,info)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(ValueError,RuntimeError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(ROOT/'live'/(gid+'.json'),r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],state['results'][gid]['modes_closed'])
