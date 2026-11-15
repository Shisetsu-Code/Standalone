"""Prepare source-price corrections, then optionally requeue only preserved init-only attempts."""
import argparse,json,shutil,urllib.request
from run_demo_qa import ROOT,PRIVATE,save,now,modes_from_init
from legacy_metadata import prove_default
from checkpoint_guard import acquire
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--enqueue',action='store_true');args=parser.parse_args();output=ROOT/'prepared-price-retries.json'
 if not args.enqueue:
  results=[]
  for f in sorted((ROOT/'live').glob('*.json')):
   r=json.loads(f.read_text(encoding='utf8'));events=r.get('events',[])
   if r.get('status')!='needs_review' or not events or any(e['request'].get('command')!='init' for e in events):continue
   initial=events[-1].get('response',{})
   if initial.get('flow',{}).get('state')!='ready' or not initial.get('options',{}).get('feature_options',{}).get('feature_multipliers'):continue
   if r.get('reason')!='Unverified feature cost schema' and r.get('error_type')!='HTTPError':continue
   try:
    metadata=prove_default(f.stem,urllib.request.build_opener());modes=modes_from_init(initial,metadata);item=dict(game_id=f.stem,status='prepared_not_executed',planned_modes=len(modes),proof='protocols/'+f.stem+'.legacy-prices.json')
   except Exception as e:item=dict(game_id=f.stem,status='pending',error_type=type(e).__name__)
   results.append(item);print(item,flush=True)
  save(output,dict(prepared_at=now(),gameplay_calls=0,results=results))
 else:
  runner_lock_handle=acquire(ROOT/'runner.lock');state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
  if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Stop between games before queue maintenance')
  prepared=json.loads(output.read_text(encoding='utf8'));changed=[]
  for item in prepared['results']:
   gid=item['game_id']
   if item['status']!='prepared_not_executed' or gid not in state['results']:continue
   result=state['results'][gid];f=ROOT/result['report'];report=json.loads(f.read_text(encoding='utf8'))
   if report.get('status')!='needs_review' or report.get('modes') or any(e['request'].get('command')!='init' for e in report['events']):raise RuntimeError('Attempt changed or has wagers: '+gid)
   metadata=json.loads((ROOT/item['proof']).read_text(encoding='utf8'));modes_from_init(report['events'][-1]['response'],metadata)
   archive=ROOT/'live'/'attempts'/(gid+'.before-basic-and-rounding-fix.json')
   if archive.exists():raise RuntimeError('Price fix already requeued: '+gid)
   archive.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,archive);source=PRIVATE/(gid+'.session.json')
   if source.exists():
    target=PRIVATE/'attempts'/(gid+'.before-basic-and-rounding-fix.session.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
   state.setdefault('prior_attempts',[]).append(dict(game_id=gid,result=result,report_archive=str(archive.relative_to(ROOT)),reason='Only init previously sent. Official basic skin path and client ceiling-price rule verified; no previous wager replay.'));del state['results'][gid];changed.append(gid)
  state['updated_at']=now();save(state_path,state);save(ROOT/'basic-rounding-requeue.json',dict(changed_at=now(),games=changed));print('Prepared price corrections queued:',changed)
