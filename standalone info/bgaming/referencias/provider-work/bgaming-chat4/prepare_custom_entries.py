"""Read-only preparation of custom demo frontend contracts; no init/play or new launch."""
import json,re,urllib.request,hashlib
from urllib.parse import urlsplit,quote
from run_demo_qa import ROOT,PRIVATE,save,trusted,now
from product_round_rpc import metadata,plan
def prepare(gid):
 data=json.loads((PRIVATE/'hyperhive'/(gid+'.session.json')).read_text(encoding='utf8'));assert data['fresh_demo'] and data['game_id']==gid;origin=trusted(data['endpoint']).rsplit('/api',1)[0];dest=PRIVATE/'research'/'frontends'/gid;dest.mkdir(parents=True,exist_ok=True)
 def get(route,name):
  path=dest/name
  if path.exists():return path.read_bytes()
  with urllib.request.urlopen(urllib.request.Request(origin+route,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as r:trusted(r.url);raw=r.read()
  path.write_bytes(raw);return raw
 frontend=get('/?token='+quote(data['token'],safe=''),'index.html').decode('utf8');scripts=re.findall(r'<script[^>]+src=[\"\x27]([^\"\x27]+)',frontend);scripts=[s for s in scripts if not urlsplit(s).netloc and re.fullmatch(r'(?:\./|/)?[A-Za-z0-9_./-]+\.js',s)]
 if len(scripts)!=1:raise ValueError('Frontend not a single JS entry')
 route='/'+scripts[0].lstrip('./');source=get(route,'entry-'+route.rsplit('/',1)[-1]).decode('utf8');initial=data.get('initial') or next(e['response'] for e in data['events'] if e['request']['method']=='init');m=metadata(source,initial['result']['config'].get('purchased_features',[]));m['entry_path']=route;m['planned_mode_count']=len(plan(initial,m));save(ROOT/'protocols'/(gid+'.product-round.json'),m);return dict(game_id=gid,status='prepared_not_executed',entry_path=route,planned_mode_count=m['planned_mode_count'],proof='protocols/'+gid+'.product-round.json')
if __name__=='__main__':
 results=[]
 for f in sorted((ROOT/'live').glob('*.json')):
  report=json.loads(f.read_text(encoding='utf8'))
  if report.get('reason')!='Public metadata HTTP 404 at /game/media/definitions.json':continue
  try:r=prepare(f.stem)
  except Exception as e:r=dict(game_id=f.stem,status='unsupported_or_fetch_pending',error_type=type(e).__name__)
  results.append(r);print(r['game_id'],r['status'],r.get('planned_mode_count',r.get('error_type')),flush=True)
 save(ROOT/'prepared-custom-entries.json',dict(prepared_at=now(),gameplay_calls=0,results=results))
