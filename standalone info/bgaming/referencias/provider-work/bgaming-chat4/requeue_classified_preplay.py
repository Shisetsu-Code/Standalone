"""One explicit fresh validation after source-corrected/pre-launch-only failures."""
import json,copy,shutil,sys
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause queue first')
 for gid in sys.argv[1:]:
  migrated=['CatsLoveYummy','RedHotChilliChickens','MysticReels','ChickenFire']
  if gid not in ['PenaltyDuelWithJulioCesar','PrincessOfSky']+migrated:raise ValueError('No reviewed pre-play contract')
  r=json.loads((ROOT/'live'/(gid+'.json')).read_text(encoding='utf8'));events=r.get('events',[])
  if r.get('modes'):raise ValueError('Already progressed; no replay')
  if gid in migrated:
   old_context=json.loads((PRIVATE/(gid+'.session.json')).read_text(encoding='utf8'))
   if len(events)!=1 or events[0]['request'].get('command')!='init' or events[0].get('status')!=404 or not old_context.get('fresh_demo') or urlsplit(old_context['page']).path!='/hyperhive' or (PRIVATE/'hyperhive'/(gid+'.session.json')).exists():raise ValueError('Not the legacy init rejected on a Hyperhive bootstrap')
  elif gid=='PrincessOfSky':
   if events or r.get('error_type')!='HTTPError':raise ValueError('Not the pre-play launch failure')
  else:
   if len(events)!=2 or events[0]['request'].get('command')!='init' or events[1].get('status')!=422 or events[1]['response']!={'errors':[{'code':203,'desc':'invalid_options'}]} or events[1]['request'].get('command')!='play' or events[1]['request'].get('options',{}).get('sector','absent') is not None:raise ValueError('Not the exact rejected null-sector attempt')
  archive=ROOT/'live/attempts'/(gid+'.before-classified-preplay-validation.json')
  if archive.exists():raise ValueError('Fresh pre-play validation already reserved')
  save(archive,copy.deepcopy(r))
  for f in [PRIVATE/(gid+'.session.json'),PRIVATE/'hyperhive'/(gid+'.session.json')]:
   if f.exists():shutil.copyfile(f,PRIVATE/'attempts'/(gid+'.'+f.parent.name+'.before-classified-preplay-validation.session.json'))
  old=state['results'].pop(gid);state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=old,report_archive=str(archive.relative_to(ROOT)),reason='Explicit fresh validation; prior attempt had no accepted gameplay. Rejected/null-sector or failed launch retained, never retried in its original session.'))
 state['updated_at']=now();save(ROOT/'run-state.json',state);print('Prepared fresh pre-play validation',sys.argv[1:])
