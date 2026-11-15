"""Offline queue maintenance: only init-only Scratch or explicitly reconciled rejected attempts."""
import json,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
TARGETS={'ChickenHalloween','SpiderCircusHoldAndWin','BlingBlitzDiamondDrop','HotRocket532','RocketEruptionTripleBlast','TheGodfather3PillarsOfPower','StarTrekNextGen','BigTunaBonanza'}
if __name__=='__main__':
 state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Runner must be stopped between games')
 changed=[]
 for gid,result in list(state['results'].items()):
  f=ROOT/result['report'];report=json.loads(f.read_text(encoding='utf8'));events=report.get('events',[]);init=next((e['response'] for e in events if e['request'].get('command')=='init' or e['request'].get('method')=='init'),None)
  if report.get('status')!='needs_review' or report.get('modes'):continue
  scratch=bool(init and isinstance(init.get('options',{}).get('bet'),int) and report.get('reason')=="'available_bets'" and all(e['request'].get('command')=='init' for e in events))
  if gid not in TARGETS and not scratch:continue
  reason='Init-only fixed-price Scratch; no prior wager. Official client play envelope is now verified per game.'
  if not scratch:
   rb=json.loads((PRIVATE/'readback'/(gid+'.json')).read_text(encoding='utf8'));r=rb['response'].get('result',rb['response']);initial=(init or {}).get('result',init or {})
   if rb['status']!=200 or r.get('balance')!=initial.get('balance') or r.get('balance') is None:raise RuntimeError('Readback did not prove unchanged balance: '+gid)
   if 'flow' in r:
    if r['flow']['state']!='ready':raise RuntimeError('Legacy round not ready: '+gid)
   elif r.get('state') is not None:raise RuntimeError('RPC open state: '+gid)
   if rb['time']<=events[-1]['time']:raise RuntimeError('Readback predates attempt: '+gid)
   reason='Later non-wagering init observed the same FUN balance and no open round. Init may renew FUN funds, so this does not prove the original POST outcome. Preserve the prior attempt and test the corrected envelope only in a new independent official demo session.'
  archive=ROOT/'live'/'attempts'/(gid+'.before-protocol-fix.json')
  if archive.exists():raise RuntimeError('Archive exists: '+gid)
  archive.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,archive)
  for private in [PRIVATE/(gid+'.session.json'),PRIVATE/'hyperhive'/(gid+'.session.json')]:
   if private.exists():
    dest=PRIVATE/'attempts'/(gid+'.'+private.parent.name+'.before-protocol-fix.session.json');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,dest)
  state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason=reason));del state['results'][gid];changed.append(gid)
 state['updated_at']=now();save(state_path,state);save(ROOT/'recovery-requeue.json',dict(changed_at=now(),games=changed,no_uncertain_post_replayed=True));print('Verified recovery games queued:',len(changed));print(', '.join(changed))
