"""Archive only init-only attempts for a corrected fresh-demo test. No network."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
if __name__=='__main__':
 state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game'):raise RuntimeError('Runner active; wait for between-game checkpoint')
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before editing queue')
 changed=[]
 for gid,result in list(state['results'].items()):
  f=ROOT/result['report'];report=json.loads(f.read_text(encoding='utf8'))
  if report.get('reason')!='Unverified feature cost schema':continue
  if not report.get('events') or any(e['request'].get('command')!='init' for e in report['events']):raise RuntimeError('Non-init attempt unexpectedly selected: '+gid)
  if report['events'][-1].get('response',{}).get('flow',{}).get('state')!='ready':raise RuntimeError('Init not ready: '+gid)
  archive=ROOT/'live'/'attempts'/(gid+'.init-only-before-price-fix.json')
  if archive.exists():raise RuntimeError('Archive already exists; no overwrite')
  archive.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,archive)
  private=PRIVATE/(gid+'.session.json')
  if private.exists():
   target=PRIVATE/'attempts'/(gid+'.init-only-before-price-fix.session.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,target)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason='Init only, no wagers. Official client price fallback is now checked per game before a new fresh FUN test.'))
  del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(state_path,state);save(ROOT/'price-requeue.json',dict(changed_at=now(),games=changed,no_prior_wager=True));print('Init-only games queued after source-price fix:',len(changed))
