"""Static client preparation only: no demo launches, session API calls, spins or purchases."""
import json,time,urllib.request,urllib.error
from run_demo_qa import ROOT,save,now
from legacy_metadata import load_client
if __name__=='__main__':
 targets=[]
 for path in sorted((ROOT/'live').glob('*.json')):
  report=json.loads(path.read_text(encoding='utf8'))
  if report.get('reason')=='HTTP rejection 422; no automatic retry':targets.append(report['game']['game_id'])
 results=[];opener=urllib.request.build_opener()
 for gid in targets:
  time.sleep(.5)
  try:
   meta,source=load_client(gid,opener);entry=dict(game_id=gid,status='static_source_available',metadata=meta,characters=len(source),scope='Preparation only; no native gameplay calls')
  except urllib.error.HTTPError as e:entry=dict(game_id=gid,status='static_source_http_error',http_status=e.code,scope='No gameplay calls; loader.js may not be the actual engine')
  except Exception as e:entry=dict(game_id=gid,status='static_source_needs_review',error_type=type(e).__name__,scope='No gameplay calls')
  results.append(entry);save(ROOT/'protocols'/(gid+'.static-client-index.json'),entry);save(ROOT/'pending-source-inspection.json',dict(updated_at=now(),gameplay_calls=0,results=results));print(gid,entry['status'],entry.get('http_status',''),flush=True)
