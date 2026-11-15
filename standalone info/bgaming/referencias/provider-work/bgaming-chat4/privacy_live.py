"""Ensure known private fresh-demo session secrets do not appear in public deliverables."""
import json,re
from run_demo_qa import ROOT,PRIVATE,save,now
def secrets(value,key=''):
 result=set()
 if isinstance(value,dict):
  for k,v in value.items():
   if isinstance(v,str) and len(v)>8 and v!='[REDACTED]' and (re.search(r'token|csrf_value|state_lock|authorization|password|secret|csid',k,re.I) or (k=='value' and 'domain' in value and 'name' in value)):result.add(v)
   result.update(secrets(v,k))
 elif isinstance(value,list):
  for v in value:result.update(secrets(v,key))
 return result
if __name__=='__main__':
 values=set();sources=0
 for f in PRIVATE.rglob('*.json'):
  try:d=json.loads(f.read_text(encoding='utf8'))
  except (ValueError,UnicodeError):continue
  values.update(secrets(d));sources+=1
 hits=[];files=0
 for f in ROOT.rglob('*'):
  if not f.is_file() or f.suffix not in ('.json','.md','.py','.txt','.html','.js','.cjs'):continue
  s=f.read_text(encoding='utf8');files+=1
  for v in values:
   if v in s:hits.append(str(f.relative_to(ROOT)));break
 result=dict(checked_at=now(),private_json_sources=sources,known_secret_values=len(values),public_files_checked=files,files_with_known_secret_matches=sorted(set(hits)),ok=not hits);save(ROOT/'privacy-live.json',result);print(json.dumps(result));raise SystemExit(1 if hits else 0)
