"""Public catalogue and new anonymous launch discovery. No wagering."""
import pathlib,json,re,hashlib,datetime
from urllib.parse import urlsplit,urljoin,parse_qs
import requests
ROOT=pathlib.Path(__file__).resolve().parent.parent
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def clean(x):
 if isinstance(x,dict):return {k:('[REDACTED]' if re.search(r'^(session|sid|sign|token|cookie|authorization|password|secret)$',k,re.I) else clean(v)) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 return x
class HTTP:
 def __init__(self):self.s=requests.Session();self.s.trust_env=False
 def request(self,url,*,data=None,path):
  if (ROOT/'private/remote-block.json').exists():raise RuntimeError('remote_block_preserved_no_new_network')
  p=ROOT/path
  if p.exists():raise ValueError('journal_exists_no_implicit_retry')
  u=urlsplit(url);j={'host':u.hostname,'path':re.sub(r'/sid/[^/]+','/sid/[REDACTED]',u.path),'query_keys':list(parse_qs(u.query)),'method':'POST' if data is not None else 'GET','request':clean(data),'status':'sending'};save(p,j)
  q=self.s.request(j['method'],url,data=data,timeout=35,allow_redirects=False);j.update(status='received',http_status=q.status_code,sha256=hashlib.sha256(q.content).hexdigest());save(p,j)
  if q.status_code in (403,429,503):save(ROOT/'private/remote-block.json',j);raise ValueError('remote_block_'+str(q.status_code))
  if q.status_code not in (200,301,302,303,307,308):raise ValueError('http_'+str(q.status_code))
  return q
 def portal(self):
  q=self.request('https://amigogaming.com/es/games',path='private/discovery/portal.json');s=q.text
  token=re.search(r'<meta name="csrf-token" content="([^"]+)',s)
  if token:self.s.headers['X-CSRF-TOKEN']=token.group(1)
  return q
 def catalogue(self):
  rows=[];total=1
  for page in range(1,101):
   q=self.request(f'https://amigogaming.com/fetchGames?offsetPage={page}&locale=es',path=f'private/discovery/catalogue-{page}.json');x=q.json();total=x['total_pages'];rows+=x['items']
   if page>=total:break
  assert len({x['id'] for x in rows})==len(rows)
  for n,g in enumerate(rows,1):g.update(ordinal=n,slug=g['url'].rstrip('/').split('/')[-1])
  save(ROOT/'results/catalogue.json',rows);print({'catalogue_entries':len(rows),'coming_soon':sum(bool(g['is_coming_soon']) for g in rows)},flush=True)
 def launch(self,g,label):
  folder=ROOT/'private/sessions'/label;folder.mkdir(parents=True,exist_ok=False)
  q=self.request('https://amigogaming.com/es/generateDemoGameLink',data={'id':g['id'],'sessionType':'desktop'},path=f'private/sessions/{label}/generate.json');url=q.text.strip()
  assert urlsplit(url).hostname=='launch.amigogaming.com'
  for n in range(12):
   u=urlsplit(url);assert u.hostname in ('launch.amigogaming.com','demo.amigogaming.online','demo.amigogaming.cloud')
   q=self.request(url,path=f'private/sessions/{label}/redirect-{n}.json')
   if q.is_redirect:url=urljoin(url,q.headers['Location']);continue
   break
  params={k:v[0] for k,v in parse_qs(urlsplit(url).query).items()};save(folder/'credentials.json',{'entry_url':url,'params':params})
  assert all(k in params for k in ['session','sign','launch'])
  body={k:params[k] for k in ['session','sign']};body.update(info='QA native HTTP/WS; Windows; anonymous demo',mobile=params.get('mobile','false'))
  q=self.request(params['launch'],data=body,path=f'private/sessions/{label}/native-launch.json');x=q.json();save(folder/'launch.private.json',x);save(folder/'launch.json',clean(x));print({'label':label,'launch_keys':list(x),'game_name':x.get('gameName')},flush=True)
  return x
if __name__=='__main__':
 h=HTTP();h.portal();h.catalogue();g=next(x for x in json.loads((ROOT/'results/catalogue.json').read_text()) if x['id']==132);h.launch(g,'diamond-raid-discovery-1')
