"""Queue three init-only games after identifying their actual shared classic client."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
from classic_slots import metadata
from old_slots import plan
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 source=(PRIVATE/'research'/'classic'/'casino.min.js').read_text(encoding='utf8');changed=[]
 for gid in ['WestTown','LuckyLadyClover','ScratchDice']:
  result=state['results'][gid];path=ROOT/result['report'];r=json.loads(path.read_text(encoding='utf8'))
  if r.get('modes') or len(r['events'])!=1 or r['events'][0]['request'].get('command')!='init':raise RuntimeError('Not an init-only attempt '+gid)
  meta=metadata(source,gid);modes=plan(r['events'][0]['response'],meta);save(ROOT/'protocols'/(gid+'.classic-slots-prepared.json'),dict(**meta,source_url='https://cdn.bgaming-network.com/html/casino.min.js',declared_modes=modes,live_status='not yet tested; a fresh launch must confirm this exact classic script before sending any wager'))
  archive=ROOT/'live'/'attempts'/(gid+'.before-classic-loader-fix.json')
  if archive.exists():raise RuntimeError('Already queued '+gid)
  save(archive,r);backup=PRIVATE/'attempts'/(gid+'.before-classic-loader-fix.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason='Init only; actual shared casino.min.js source has explicit game registration/native indexed bet contract. Fresh launch must confirm classic script before wagering. No previous wager replay.'));del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(ROOT/'run-state.json',state);save(ROOT/'classic-loader-requeue.json',dict(updated_at=now(),games=changed));print('Classic source cases queued',changed)
