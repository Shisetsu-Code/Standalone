"""Fetch immutable-looking official CDN client resources, never session APIs."""
import urllib.request,json,hashlib,re,sys
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save
if __name__=='__main__':
 gid=sys.argv[1];assert re.fullmatch('[A-Za-z0-9_-]+',gid)
 routes=sys.argv[2:] or ['loader.js']
 for route in routes:
  assert not route.startswith('/') and '..' not in route and '?' not in route
  url='https://cdn.bgaming-network.com/html/'+gid+'/'+route
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as r:raw=r.read();assert urlsplit(r.url).hostname=='cdn.bgaming-network.com'
   dest=PRIVATE/'research'/'legacy'/gid/route;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
   save(ROOT/'protocols'/(gid+'.'+route.replace('/','_')+'.cdn.json'),dict(url=url,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()));print(gid,route,len(raw),flush=True)
  except Exception as e:print(gid,route,type(e).__name__,flush=True)
