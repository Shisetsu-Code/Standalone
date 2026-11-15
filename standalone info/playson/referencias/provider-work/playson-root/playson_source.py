"""Static native-source bindings; provider JavaScript is parsed, never executed."""
import re,json
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup

def title_key(value):return re.sub('[^a-z0-9]','',value.casefold())

def inspect_bet_builders(source):
 bodies=[];choice_action='game'if 'createChoiceMessage=function'in source and 'createMessage(this.status="game")'in source else None
 for match in re.finditer(r'createBetMessage=function\([^)]*\)\{',source):
  start=match.end();depth=1;quote=None;escaped=False;end=start
  for end in range(start,len(source)):
   c=source[end]
   if quote:
    if escaped:escaped=False
    elif c=='\\':escaped=True
    elif c==quote:quote=None
   elif c in ['"',"'",'`']:quote=c
   elif c=='{':depth+=1
   elif c=='}':
    depth-=1
    if depth==0:break
  if depth:return {'supported':False,'reason':'Unclosed native bet builder'}
  bodies.append(source[start:end])
 if not bodies:return {'supported':False,'reason':'Native bet builder not found'}
 buy=False;ante=False;styles=set()
 for body in bodies:
  tags=set(re.findall(r'<([A-Za-z_][A-Za-z0-9_]*)',body))
  if 'connection.createMessage('in body:
   if not tags.issubset({'bet','buy','chance_booster','player_choice'})or 'bet'not in tags or '.attr("cash",'not in body:return {'supported':False,'reason':'Unknown base bet XML'}
   if set(re.findall(r'\.attr\("([^"]+)"',body))!={'cash'}:return {'supported':False,'reason':'Unknown base bet attributes'}
  elif '.prototype.createBetMessage.call('in body:
   if not tags.issubset({'buy','chance_booster','player_choice'})or '.attr('in body:return {'supported':False,'reason':'Unknown custom stake XML'}
  else:return {'supported':False,'reason':'Unknown native bet builder inheritance'}
  if 'player_choice'in tags and not choice_action:return {'supported':False,'reason':'Unknown conditional choice command'}
  if 'buy'in tags:
   if 'buyFeature'not in body:return {'supported':False,'reason':'Unknown purchase UI confirmation'}
   if 'bonus_game="true"'in body:styles.add('untyped_bonus_game')
   elif 'freegame="true"'in body:
    if 'featureType'in body or'buyFeatureType'in body:styles.add('typed')
    elif 'type="0"'in body:styles.add('fixed_zero')
    elif 'type='not in body:styles.add('untyped_freegame')
    else:return {'supported':False,'reason':'Unknown typed purchase binding'}
   else:return {'supported':False,'reason':'Unknown purchase XML namespace'}
  buy|='buy'in tags;ante|='chance_booster'in tags
 if len(styles)>1:return {'supported':False,'reason':'Ambiguous native purchase styles'}
 return {'supported':True,'bonus_round_counter':'bonusRound++'in source and 'createMessage("bonus")'in source and 'attr("round",'in source,'choice_action':choice_action,'purchase_style':next(iter(styles),'none'),'purchase_binding':buy,'ante_binding':ante,'bet_builders':len(bodies),'schema':'native XML base + typed freegame purchases + quoted chance booster'}

def parse_launch(html,expected_title):
 m=re.search(r'partner:\s*',html)
 if not m:raise ValueError('Official demo config absent')
 cfg=json.JSONDecoder().raw_decode(html[m.end():])[0]
 if not re.fullmatch(r'TEST\d+',cfg.get('key',''))or cfg.get('wl')!='demomode'or cfg.get('server_url')!='https://demo.0y81pm-c-o6pywcq.com':raise ValueError('Only public TEST demos permitted')
 if title_key(cfg.get('title',''))!=title_key(expected_title):raise ValueError('Canonical demo title mismatch')
 soup=BeautifulSoup(html,'html.parser');base=soup.find('base')['href'];game=re.search(r'gamescript:\s*"([^"]+)"',html).group(1);launcher=next(n['src']for n in soup.select('script[src]')if n['src'].startswith('launcher.'))
 for name in [game,launcher]:
  if not re.fullmatch(r'(?:game|launcher)\.[a-zA-Z0-9]+\.js',name):raise ValueError('Unknown native script route')
 if urlsplit(base).hostname!='games.box-int-54f2g.com'or '/'+cfg['game']+'/'not in urlsplit(base).path:raise ValueError('Unbound game asset owner')
 return cfg,urljoin(base,game),urljoin(base,launcher)

def native_build(html,launcher):
 m=re.search(r'@playson-games/unicore.{0,80}?version[^0-9]{1,12}([0-9]+\.[0-9]+)\.[0-9]+',launcher)
 version=re.search(r'\bversion:\s*"([^"]+)"',html);date=re.search(r'\bdate:\s*([0-9]+)',html)
 if not(m and version and date):raise ValueError('Native engine build metadata absent')
 return m.group(1),{'build_date':date.group(1),'build_version':version.group(1)}


def native_game_multiplier(launcher):
 values=[]
 for m in re.finditer(r"JSON\.parse\('((?:\\.|[^'\\])*)'\)",launcher):
  try:obj=json.loads(m.group(1).replace("\\'","'"))
  except ValueError:continue
  if isinstance(obj,dict)and all(k in obj for k in ['columns','rows','lines']):
   value=obj.get('multiplicator')or obj['lines']
   if type(value)is int and value>0:values.append(value)
 if len(set(values))==1:return values[0]
 return None
