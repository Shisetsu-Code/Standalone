"""Archive only RecycleRiches's init-only failure before source cache-query parsing fix."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 gid='RecycleRiches';old=state['results'][gid];path=ROOT/old['report'];r=json.loads(path.read_text(encoding='utf8'));archive=ROOT/'live/attempts/RecycleRiches.before-cache-query-discovery.json';p=PRIVATE/'hyperhive'/(gid+'.session.json');d=json.loads(p.read_text(encoding='utf8'))
 if archive.exists() or r.get('modes') or r.get('reason')!='Custom RPC source entry not uniquely recognized' or len(r['events'])!=1 or r['events'][0]['request'].get('method')!='init' or not d.get('fresh_demo') or d.get('status')!='received' or d.get('last_result',{}).get('state') is not None:raise RuntimeError('Not the received non-wagering source-route failure')
 save(archive,r);backup=PRIVATE/'attempts/RecycleRiches.before-cache-query-discovery.session.json';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,backup);state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=old,report_archive=str(archive.relative_to(ROOT)),reason='Init only, no play. Source entry cache hash query parsing regression fixed and tested. Fresh FUN test next; no old request replay.'));del state['results'][gid];state['updated_at']=now();save(ROOT/'run-state.json',state);print('RecycleRiches init-only route failure archived and queued')
