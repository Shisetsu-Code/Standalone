"""Read official static client resources for a fresh local QA context."""
import json,urllib.request,sys,hashlib,re
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save,trusted
if __name__=='__main__':
 gid=sys.argv[1];data=json.loads((PRIVATE/'hyperhive'/(gid+'.session.json')).read_text(encoding='utf8'));assert data['fresh_demo'];origin=trusted(data['endpoint']).rsplit('/api',1)[0];out=PRIVATE/'research'/'frontends'/gid;out.mkdir(parents=True,exist_ok=True)
 for route in sys.argv[2:]:
  assert route.startswith('/') and '?' not in route and '..' not in route and not urlsplit(route).netloc
  try:
   with urllib.request.urlopen(urllib.request.Request(origin+route,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as r:raw=r.read()
   name=route.lstrip('/').replace('/','_');(out/name).write_bytes(raw);save(ROOT/'protocols'/(gid+'.'+name+'.resource.json'),dict(route=route,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()));print(route,len(raw),flush=True)
  except Exception as e:print(route,type(e).__name__,flush=True)
