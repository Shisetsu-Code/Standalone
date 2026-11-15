"""Fetch only JS scripts explicitly referenced by cached official demo HTML. No launches/API calls."""
import json,re,hashlib,urllib.request,urllib.error
from urllib.parse import urlsplit,urljoin,quote
from run_demo_qa import ROOT,PRIVATE,save,trusted,now
def inspect(gid):
 data=json.loads((PRIVATE/'hyperhive'/(gid+'.session.json')).read_text(encoding='utf8'))
 if not data.get('fresh_demo') or data['game_id']!=gid:raise ValueError('Not a suite-owned FUN context')
 origin=trusted(data['endpoint']).rsplit('/api',1)[0];dest=PRIVATE/'research/frontends'/gid;page=dest/'index.html'
 if not page.exists():
  try:
   with urllib.request.urlopen(urllib.request.Request(origin+'/?token='+quote(data['token'],safe=''),headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
    if urlsplit(response.url).netloc!=urlsplit(origin).netloc:raise ValueError('Unexpected frontend redirect')
    raw=response.read()
   dest.mkdir(parents=True,exist_ok=True);page.write_bytes(raw)
  except Exception as error:return dict(game_id=gid,status='frontend_read_pending',error_type=type(error).__name__,resources=[])
 html=page.read_text(encoding='utf8');results=[]
 for script in re.findall(r'<script[^>]+src=[\"\x27]([^\"\x27]+)',html):
  u=urlsplit(urljoin(origin+'/',script))
  if u.scheme!='https' or u.netloc!=urlsplit(origin).netloc or not u.path.endswith('.js') or u.fragment or (u.query and not re.fullmatch('[a-f0-9]{8,64}',u.query)):continue
  url=origin+u.path+('?' +u.query if u.query else '');name='review-'+hashlib.sha256(u.path.encode()).hexdigest()[:12]+'-'+u.path.rsplit('/',1)[-1];path=dest/name
  item=dict(path=u.path)
  try:
   if path.exists():raw=path.read_bytes()
   else:
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
     final=urlsplit(response.url)
     if final.netloc!=u.netloc or final.scheme!='https':raise ValueError('Unexpected static source redirect')
     raw=response.read()
    if len(raw)>20_000_000:raise ValueError('Static resource exceeds review bound')
    path.write_bytes(raw)
   raw.decode('utf8');item.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),cache_file=name,status='cached_not_executed')
  except urllib.error.HTTPError as error:item.update(status='http_error',http_status=error.code)
  except Exception as error:item.update(status='needs_review',error_type=type(error).__name__)
  results.append(item)
 return dict(game_id=gid,status='static_review_only',resources=results)
if __name__=='__main__':
 results=[]
 for path in sorted((ROOT/'live').glob('*.json')):
  report=json.loads(path.read_text(encoding='utf8'))
  if report['status']!='needs_review' or not (PRIVATE/'hyperhive'/(path.stem+'.session.json')).exists():continue
  item=inspect(path.stem);results.append(item);print(path.stem,[(r['path'],r['status']) for r in item['resources']],flush=True)
 save(ROOT/'remaining-rpc-resources.json',dict(checked_at=now(),new_game_launches=0,gameplay_calls=0,resources_executed=0,results=results))
