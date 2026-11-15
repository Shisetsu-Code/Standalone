"""Build a provider-only coverage matrix from public catalog and sanitized evidence."""
import json
from pathlib import Path
from datetime import datetime,timezone
P=Path(__file__).parent
if __name__=='__main__':
 catalog=json.loads((P/'catalog-live.json').read_text(encoding='utf8'));entries=[]
 for g in catalog['games']:
  gid=g['game_id'];report_path=P/'live'/(str(gid)+'.json');entry={k:g[k] for k in ('game_id','title','game_type','product_url','demo_url')}
  entry.update(status='queued' if gid else 'no_public_demo_link',modes_closed=0,in_current_scope=g.get('game_type')=='Slots',scope_status='current_slot_scope' if g.get('game_type')=='Slots' else 'historical_excluded_by_user')
  if gid and report_path.exists():
   r=json.loads(report_path.read_text(encoding='utf8'));entry.update(status=r['status'],modes_closed=sum(x['status']=='closed' for x in r.get('modes',[])),modes_declared=len(r.get('declared_modes',[])),report='live/'+gid+'.json',reason=r.get('reason'))
  entries.append(entry)
 result=dict(updated_at=datetime.now(timezone.utc).isoformat(),products=len(entries),demos=290,current_scope='Slots only; other categories are preserved historical evidence',closed_modes=sum(e['modes_closed'] for e in entries),status_counts={status:sum(x['status']==status for x in entries) for status in sorted({x['status'] for x in entries})},games=entries)
 (P/'coverage-live.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in result.items() if k!='games'}))
