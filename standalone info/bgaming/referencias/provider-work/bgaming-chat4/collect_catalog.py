"""Fetch public catalog only. Does not open games or execute gameplay."""
import json,re,html,urllib.request,time,hashlib
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parent
BASE='https://bgaming.com/wp-json/bg/v1/games/search'
PARAMS=dict(sort='release_date',order='DESC',posts_per_page=25,format='html',columns_style=1,game_type=1,game_label=1,most_popular=0,ver=1493,filter='game',lang='en')
def parse_cards(t):
 result=[]
 for block in re.split(r'<div\s+role="group"',t)[1:]:
  if 'data-catalog-card' not in block.split('>',1)[0]:continue
  m=re.search(r'https://demo.bgaming-network.com/play/([^/"?]+)/FUN',block)
  product=re.search(r'https://bgaming.com/games/([^"?\s]+)',block)
  if not product:continue
  title=re.search(r'class="heading-35 also_like"[^>]*>(.*?)</div>',block,re.S)
  typ=re.search(r'class="game-type-text[^"<>]*"[^>]*>(.*?)</div>',block,re.S)
  result.append(dict(provider='bgaming',game_id=m[1] if m else None,title=html.unescape(re.sub('<[^>]+>','',title[1])).strip() if title else product[1],game_type=html.unescape(typ[1]).strip() if typ else None,product_url='https://bgaming.com/games/'+product[1],demo_url=f'https://demo.bgaming-network.com/play/{m[1]}/FUN?server=demo' if m else None,coming_soon='Coming soon' in block))
 return result
if __name__=='__main__':
 games={};pages=[];page=1
 while True:
  url=BASE+'?'+urlencode(dict(PARAMS,page=page))
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as response:raw=response.read()
  data=json.loads(raw);cards=parse_cards(data.get('html',''));meta={k:v for k,v in data.items() if k!='html'}
  pages.append(dict(page=page,url=url,metadata=meta,cards=len(cards),response_sha256=hashlib.sha256(raw).hexdigest()))
  for c in cards:
   key=c['product_url'];games.setdefault(key,dict(c,catalog_pages=[]))['catalog_pages'].append(page)
  result=dict(provider='bgaming',source='public-live-catalog',fetched_at=datetime.now(timezone.utc).isoformat(),games=list(games.values()),coverage=dict(pages=pages,complete_pagination=not data.get('hasMore',False),unique_products=len(games),with_demo=sum(bool(x['demo_url']) for x in games.values()),without_demo=sum(not x['demo_url'] for x in games.values()),filters=PARAMS))
  (ROOT/'catalog-live.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
  print('page',page,'cards',len(cards),'unique',len(games),'hasMore',data.get('hasMore'),flush=True)
  if not data.get('hasMore',False):break
  if not cards or page>=100:raise RuntimeError('Pagination guard; incomplete')
  page+=1;time.sleep(1)
