"""Queue explicitly prepared protocol corrections, preserving every previous attempt."""
import json,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now
TARGETS=['SpiderCircusHoldAndWin','ChickenHalloween','TheGodfather3PillarsOfPower','GatesOfPower','StarTrekNextGen','CluckingHell']
if __name__=='__main__':
 path=ROOT/'run-state.json';state=json.loads(path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Runner must be stopped between games')
 changed=[]
 selected=sys.argv[1:] or TARGETS
 if not set(selected)<=set(TARGETS):raise ValueError('Unprepared protocol target')
 for gid in selected:
  if gid not in state['results']:continue
  result=state['results'][gid];report_path=ROOT/result['report'];report=json.loads(report_path.read_text(encoding='utf8'))
  if report.get('status')!='needs_review' or report.get('modes'):raise RuntimeError('Do not discard completed modes: '+gid)
  for event in report['events']:
   q=event['request'];r=event.get('response',{})
   if q.get('command')=='init' or q.get('method')=='init':continue
   if event.get('status')==422 and r.get('errors')==[{'code':203,'desc':'invalid_options'}]:continue
   if q.get('method')=='play' and 'error' in r and 'result' not in r:continue
   raise RuntimeError('Attempt includes an unclassified gameplay result: '+gid)
  if gid in ('SpiderCircusHoldAndWin','ChickenHalloween') and not (ROOT/'protocols'/(gid+'.native-variants.json')).exists():raise RuntimeError('Native mode proof missing: '+gid)
  if gid=='CluckingHell' and not (ROOT/'protocols'/(gid+'.product-round.json')).exists():raise RuntimeError('Product mode proof missing')
  archive=ROOT/'live'/'attempts'/(gid+'.before-source-protocol-retest.json')
  if archive.exists():raise RuntimeError('Retest already queued: '+gid)
  archive.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(report_path,archive)
  for source in [PRIVATE/(gid+'.session.json'),PRIVATE/'hyperhive'/(gid+'.session.json')]:
   if source.exists():
    target=PRIVATE/'attempts'/(gid+'.'+source.parent.name+'.before-source-protocol-retest.session.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason='Official client wire format/source mapping corrected and regression-tested. Previous init/rejection is retained; new independent official FUN session, no original POST replay or assumption about historical balance effects.'));del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(path,state);save(ROOT/'prepared-protocol-requeue.json',dict(changed_at=now(),games=changed));print('Prepared protocol corrections queued:',changed)
