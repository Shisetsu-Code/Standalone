"""Read-only client identification of our fresh demo contexts; never sends init/play."""
import json,urllib.request,hashlib,re
from pathlib import Path
from urllib.parse import urlsplit,quote
from run_demo_qa import ROOT,PRIVATE,save,now,trusted
def inspect(gid):
 p=PRIVATE/'hyperhive'/(gid+'.session.json');data=json.loads(p.read_text(encoding='utf8'));assert data['fresh_demo']
 origin=trusted(data['endpoint']).rsplit('/api',1)[0];root=PRIVATE/'research'/'frontends'/gid;root.mkdir(parents=True,exist_ok=True)
 result=dict(game_id=gid,checked_at=now(),resources=[])
 routes=[('/?token='+quote(data['token'],safe=''),'index.html'),('/game/game.min.js','game.js'),('/assets/main/index.js','cocos.js'),('/client.min.js','client.js'),('/common.min.js','common.js'),('/game/media/definitions.json','definitions.json')]
 for route,name in routes:
  try:
   with urllib.request.urlopen(urllib.request.Request(origin+route,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as r:raw=r.read()
   (root/name).write_bytes(raw);s=raw.decode('utf8');result['resources'].append(dict(path=urlsplit(route).path,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
   if name=='index.html':
    result['cocos']='src/import-map.json' in s and 'System.import' in s
    for script in re.findall(r'<script[^>]+src=[\"\x27]([^\"\x27]+)',s):
     u=urlsplit(script)
     if not u.netloc and u.path.endswith('.js'):
      path='/'+u.path.lstrip('./')
      if path not in [a for a,b in routes]:routes.append((path,'entry-'+path.rsplit('/',1)[-1]))
  except Exception as e:result['resources'].append(dict(path=urlsplit(route).path,error_type=type(e).__name__))
 save(ROOT/'protocols'/(gid+'.frontend.json'),result);print(gid,'cocos',result.get('cocos'),'resources',[(r['path'],r.get('bytes',r.get('error_type'))) for r in result['resources']],flush=True)
if __name__=='__main__':
 import sys
 for gid in sys.argv[1:]:inspect(gid)
