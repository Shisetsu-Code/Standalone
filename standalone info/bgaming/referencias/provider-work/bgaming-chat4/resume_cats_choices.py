"""Finish only Cats Soup's already-paid bonus after an exact readback/source match."""
import json,time,copy,shutil
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore_rejected_continuation,adopt_observed_init
from legacy_metadata import load_client
from cats_choices import metadata,next_choice
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='CatsSoup';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 d,r=restore_rejected_continuation(gid,422,203,'invalid_options','play_bonus',None)
 info,source=load_client(gid,d.opener);info.update(metadata(source));mode=r['declared_modes'][len(r['modes'])];trigger=len(r['events'])-2
 if len(r['modes'])!=1 or mode['options']!={'bet':20,'purchased_feature':'bonus_buy'} or r['events'][trigger]['request'].get('options')!=mode['options'] or d.last_response['flow']['state']!='play_bonus':raise ValueError('Existing paid Cats Soup trigger differs; no new purchase')
 archive=ROOT/'live/attempts/CatsSoup.before-indexed-choice.json'
 if archive.exists():raise RuntimeError('Recovery already attempted; do not repeat')
 current=adopt_observed_init(d,r,gid);next_choice(current,info)
 save(archive,copy.deepcopy(json.loads((ROOT/'live/CatsSoup.json').read_text(encoding='utf8'))));backup=PRIVATE/'attempts/CatsSoup.before-indexed-choice.session.json';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/'CatsSoup.session.json',backup)
 d.active_mode=mode;d.protocol_metadata=info
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live/CatsSoup.json';r.update(status='running',protocol_metadata=info,events=d.events);r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  final=d.settle(current);d.prev=final;r['modes'].append(dict(mode=mode,status='closed',first_event=trigger,last_event=len(d.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True,choice_actions=getattr(d,'choice_actions',[])))
  r['status']=completion_status(r,info)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
