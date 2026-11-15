"""Offline BGaming HAR analysis. No networking, no execution of captured code."""
import json,re,hashlib,base64,html
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parent
NAMES=['bgaming.com_Archive [26-10-29 00-03-36].har','demo.bgaming-network.com_Archive [26-10-29 00-08-38].har','bgaming.com_Archive [26-10-29 00-15-41].har']
def dump(name,obj): (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def textbody(e):
 c=e['response'].get('content',{}); t=c.get('text','')
 return '' if c.get('encoding')=='base64' else t
class Sanitizer:
 def __init__(self): self.alias={}
 def clean(self,v,key=''):
  if key in ('round_id','last_action_id','round_series_id'):
   if v is None:return None
   k=(key,str(v));self.alias.setdefault(k,f'{key}-{sum(1 for x in self.alias if x[0]==key)+1}');return self.alias[k]
  if key=='csid' or re.search(r'token|cookie|session|password|secret|authorization|player_id|player_uuid|user_id|t_key|state_lock',key,re.I):return '[REDACTED]'
  if isinstance(v,dict):return {k:self.clean(x,k) for k,x in v.items()}
  if isinstance(v,list):return [self.clean(x,key) for x in v]
  if isinstance(v,str) and ('http' in v or re.search(r'[0-9a-f]{8}-[0-9a-f-]{27,}',v,re.I)):return '[REDACTED_STRING]'
  return v

def normalize(row):
 r=row['response'];q=row['request'];f=r.get('flow',{});o=r.get('outcome',{});b=r.get('balance',{})
 return dict(source=row['source'],entry=row['entry'],game=row['game'],session=row['session'],command=q.get('command'),request_options=q.get('options'),round=f.get('round_id'),state=f.get('state'),available_actions=f.get('available_actions',[]),wallet=b.get('wallet'),game_balance=b.get('game'),bet=o.get('bet'),win=o.get('win'),features=r.get('features',{}),http_status=row['status'])

def analyze(desktop):
 games=defaultdict(list);sources=[];catalog={};pages=[];launch=[];versions=defaultdict(set)
 for si,name in enumerate(NAMES):
  p=desktop/name;raw=p.read_bytes();es=json.loads(raw.decode('utf-8-sig'))['log']['entries'];s=Sanitizer();sessions={};hosts=Counter();ws=[]
  for i,e in enumerate(es):
   u=urlsplit(e['request']['url']);hosts[u.hostname]+=1;t=textbody(e);status=e['response']['status']
   if u.scheme in ('ws','wss') or e.get('_webSocketMessages'):ws.append(i)
   m=re.search(r'/html/([^/]+)/(v[^/]+)/',u.path)
   if m:versions[m[1]].add(m[2])
   if u.hostname=='demo.bgaming-network.com' and not u.path.startswith('/api/'):
    if e['response'].get('content',{}).get('mimeType','').startswith('text/html') or u.path.startswith('/play/'):
     launch.append(dict(source=si,entry=i,status=status,method=e['request']['method'],host=u.hostname,path=re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27,}','{id}',u.path),query_keys=sorted(parse_qs(u.query))))
   card_text=t
   try:
    payload=json.loads(t)
    if isinstance(payload,dict) and isinstance(payload.get('html'),str):card_text=payload['html']
   except (ValueError,TypeError):pass
   if 'data-catalog-card' in card_text:
    for block in re.split(r'<div\s+role="group"',card_text)[1:]:
     if 'data-catalog-card' not in block.split('>',1)[0]:continue
     m=re.search(r'https://demo.bgaming-network.com/play/([^/"?]+)/FUN',block)
     demo_id=m[1] if m else None
     fallback=re.search(r'https://bgaming.com/games/([^"?\s]+)',block)
     if not demo_id and not fallback:continue
     gid=demo_id or ('product:'+fallback[1]);title=re.search(r'class="heading-35 also_like"[^>]*>(.*?)</div>',block,re.S);url=re.search(r'https://bgaming.com/games/([^"?\s]+)',block)
     item=catalog.setdefault(gid,dict(provider='bgaming',game_id=demo_id,title=html.unescape(re.sub('<[^>]+>','',title[1])).strip() if title else gid,demo_url=f'https://demo.bgaming-network.com/play/{gid}/FUN?server=demo' if demo_id else None,product_url='https://bgaming.com/games/'+url[1] if url else None,evidence=[]))
     ref=dict(source=si,entry=i)
     if ref not in item['evidence']:item['evidence'].append(ref)
   if '/wp-json/bg/v1/games/search' in u.path:
    meta={}
    try:meta={k:v for k,v in json.loads(t).items() if k!='html'}
    except:pass
    pages.append(dict(source=si,entry=i,status=status,query=parse_qs(u.query),metadata=meta))
   if u.hostname!='demo.bgaming-network.com' or not u.path.startswith('/api/'):continue
   parts=u.path.split('/');gid=parts[2]
   try:q=json.loads(e['request'].get('postData',{}).get('text','{}'));r=json.loads(t)
   except:continue
   if q.get('command') not in ('init','spin','freespin','respin','close_session'):continue
   # Session values remain only in RAM; fixtures carry local, non-reusable aliases.
   session='/'.join(parts[3:]);sessions.setdefault(session,f'capture-{si}-session-{len(sessions)+1}')
   games[gid].append(dict(source=si,entry=i,time=e['startedDateTime'],game=gid,session=sessions[session],method=e['request']['method'],status=status,endpoint=f'https://demo.bgaming-network.com/api/{gid}/{{session}}/{{key}}',request=s.clean(q),response=s.clean(r)))
  sources.append(dict(source=si,name=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),entries=len(es),hosts=dict(hosts),websocket_entries=ws))
 dump('sources.json',sources);dump('catalog.json',dict(games=list(catalog.values()),coverage=dict(unique_cards=len(catalog),pages=pages,note='Captured cards only; metadata total is not assumed to mean game count. No full-catalog completeness claim.')));dump('launch.json',launch)
 summary={};allrounds=[];checks=[]
 for gid,rows in games.items():
  dump(gid+'.reference.json',rows);norm=[normalize(x) for x in rows];dump(gid+'.normalized.json',norm)
  inits=[x for x in rows if x['request'].get('command')=='init'];opts=inits[-1]['response']['options'] if inits else {};prev={};rounds={}
  multipliers=opts.get('feature_options',{}).get('feature_multipliers',{})
  for row,n in zip(rows,norm):
   if n['wallet'] is None:continue
   old=prev.get(n['session']);q=n['request_options'] or {};cmd=n['command'];cost=0
   if cmd=='spin':
    cost=q['bet'];feature=q.get('purchased_feature')
    if feature:
     mult=multipliers[feature]
     if isinstance(mult,dict):mult=mult[q['purchased_feature_level']]
     numerator=q['bet']*mult
     if numerator % multipliers['base_bet']:raise ValueError('Unverified fractional purchase cost')
     cost=numerator//multipliers['base_bet']
   if old and cmd!='init':
    credit=old['game_balance'] if old['state']=='closed' else 0
    expected=old['wallet']+credit-cost
    checks.append(dict(game=gid,source=row['source'],entry=row['entry'],kind='wallet',expected=expected,actual=n['wallet'],ok=expected==n['wallet'],cost_native=cost,previous_closed_credit_native=credit))
    if cmd in ('freespin','respin'):
     expected=old['game_balance']+n['win'];checks.append(dict(game=gid,source=row['source'],entry=row['entry'],kind='game_accumulator',expected=expected,actual=n['game_balance'],ok=expected==n['game_balance']))
    checks.append(dict(game=gid,source=row['source'],entry=row['entry'],kind='allowed_command',ok=cmd in old['available_actions']))
   if cmd in ('spin','freespin','respin'):
    key=(n['session'],n['round']);rr=rounds.setdefault(key,dict(game=gid,source=row['source'],round=n['round'],start_entry=row['entry'],commands=[],cost_native=cost,win_native=0,closed=False,feature=q.get('purchased_feature'),level=q.get('purchased_feature_level')));rr['commands'].append(cmd);rr['win_native']+=n['win'];rr['closed']=n['state']=='closed';rr['end_entry']=row['entry'];rr['final_game_native']=n['game_balance']
   prev[n['session']]=n
  allrounds.extend(rounds.values());summary[gid]=dict(api_calls=len(rows),commands=dict(Counter(x['request'].get('command') for x in rows)),asset_versions=sorted(versions[gid]),currency=opts.get('currency'),available_bets=opts.get('available_bets'),default_bet=opts.get('default_bet'),minimum_bet_native=min(opts['available_bets']) if opts else None,feature_options=opts.get('feature_options'),rounds=len(rounds),closed_rounds=sum(x['closed'] for x in rounds.values()))
 dump('reconciliation.json',dict(checks=checks,passed=sum(x['ok'] for x in checks),failed=sum(not x['ok'] for x in checks),rounds=allrounds));dump('summary.json',dict(provider='bgaming',games=summary,catalog_cards=len(catalog),verified=['Original HAR hashes','Native FUN currency and bets','Recorded purchase costs','Captured round transitions and balance checks'],pending=['Fresh launch session creation in live QA','Uncaptured catalog pages','Unobserved choices and cashout','Generalization beyond two games'],execution_policy=dict(offline=True,new_gameplay_calls=0,max_games_per_minute=1)))
 print(json.dumps(dict(games=summary,catalog_cards=len(catalog),checks=len(checks),failures=[x for x in checks if not x['ok']],rounds=allrounds),indent=2))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--desktop',type=Path,default=Path('C:/Users/Shisetsu/Desktop'));a=p.parse_args();analyze(a.desktop)

