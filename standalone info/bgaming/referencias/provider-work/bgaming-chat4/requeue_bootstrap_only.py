"""Archive non-wagering attempts affected by the now-tested metadata import regression."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
if __name__=='__main__':
 p=ROOT/'run-state.json';state=json.loads(p.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Runner must be stopped between games')
 changed=[]
 for gid,result in list(state['results'].items()):
  report_path=ROOT/result['report'];r=json.loads(report_path.read_text(encoding='utf8'))
  if r.get('error_type')!='UnboundLocalError':continue
  if not r.get('events') or any(e['request'].get('command')!='init' for e in r['events']):raise RuntimeError('A wagering attempt must not be requeued: '+gid)
  target=ROOT/'live'/'attempts'/(gid+'.bootstrap-import-regression.json')
  if target.exists():raise RuntimeError('Regression archive already exists: '+gid)
  target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(report_path,target)
  private=PRIVATE/(gid+'.session.json')
  if private.exists():
   copy=PRIVATE/'attempts'/(gid+'.bootstrap-import-regression.session.json');copy.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,copy)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(target.relative_to(ROOT)),reason='Only init was sent; metadata import regression fixed and bootstrap path regression-tested. No wager replay.'));del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(p,state);save(ROOT/'bootstrap-requeue.json',dict(changed_at=now(),games=changed,no_prior_wager=True));print('Non-wagering bootstrap attempts requeued:',changed)
