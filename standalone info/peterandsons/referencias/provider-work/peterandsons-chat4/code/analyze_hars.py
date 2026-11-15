"""Read user HAR evidence offline. Never sends or replays requests."""
import base64
from collections import Counter
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qsl

ROOT=Path(__file__).resolve().parent.parent
SOURCES=[Path('C:/Users/Shisetsu/Desktop')/('www.peterandsonsgames.com_Archive [26-11-01 '+stamp+'].har') for stamp in ('10-14-33','10-17-34','10-20-25')]
SECRET={'token','key','authorization','cookie','set-cookie','playerid','sessionid','session','accesstoken','refreshtoken'}

def clean(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower().replace('_','').replace('-','') in {s.replace('-','') for s in SECRET} else clean(v)) for k,v in value.items()}
    if isinstance(value,list):return [clean(v) for v in value]
    return value

def content(entry):
    body=entry['response'].get('content',{})
    text=body.get('text','')
    return base64.b64decode(text).decode('utf8',errors='replace') if body.get('encoding')=='base64' else text

def parse(text):
    try:return json.loads(text)
    except (ValueError,TypeError):return {'non_json_bytes':len(text or '')}

def save(relative,value):
    p=ROOT/relative;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def flight_games(text):
    pieces=[]
    for raw in re.findall(r'self\.__next_f\.push\((\[.*?\])\)</script>',text,re.S):
        try:value=json.loads(raw)
        except ValueError:continue
        if len(value)>1 and isinstance(value[1],str):pieces.append(value[1])
    found=[]
    def walk(obj):
        if isinstance(obj,dict):
            games=obj.get('games')
            if isinstance(games,list) and games and all(isinstance(g,dict) and 'title' in g and 'slug' in g and 'gameType' in g for g in games):found.append(games)
            for value in obj.values():walk(value)
        elif isinstance(obj,list):
            for value in obj:walk(value)
    for line in ''.join(pieces).splitlines():
        if ':' not in line:continue
        try:walk(json.loads(line.split(':',1)[1]))
        except ValueError:continue
    return max(found,key=len) if found else []

def main():
    inventories=[];traces=[];catalogue={}
    for source in SOURCES:
        raw=source.read_bytes();entries=json.loads(raw)['log']['entries'];api=[]
        for index,entry in enumerate(entries):
            req=entry['request'];url=urlsplit(req['url']);text=content(entry)
            if url.hostname=='www.peterandsonsgames.com' and url.path=='/games' and 'text/html' in entry['response'].get('content',{}).get('mimeType',''):
                (ROOT/'private/catalogue.html').write_text(text,encoding='utf8')
                games=flight_games(text)
                if games:save('private/catalogue-records.json',games)
                for ordinal,game in enumerate(games,1):
                    slug=game['slug']
                    launch=urlsplit(game.get('demoUrl') or '')
                    params=dict(parse_qsl(launch.query));native_id=params.get('gameId')
                    valid=(launch.scheme=='https' and launch.hostname in ('peterandsons.org','peterandsonsgames.com') and launch.path=='/launcher.html' and native_id and re.fullmatch('[a-z0-9-]+',native_id) and params.get('wallet','demo') in ('demo','demo-preview'))
                    catalogue[slug]={'ordinal':ordinal,'id':slug,'title':game['title'],'page_url':'https://www.peterandsonsgames.com/games/'+slug,
                                     'game_type':game['gameType'],'classification':'slot' if game.get('stats',{}).get('reelConfiguration') else 'unknown',
                                     'game_id':native_id,'wallet':params.get('wallet','demo'),'valid_public_demo_link':bool(valid),
                                     'status':'pending','demo_link_present':bool(game.get('demoUrl')),
                                     'mechanics':clean(game.get('mechanics')),'stats':clean(game.get('stats')),'features':clean(game.get('features'))}
                for match in re.finditer(r'href=["\']([^"\']+)["\']',text):
                    href=unescape(match.group(1));path=urlsplit(href).path
                    hit=re.fullmatch(r'(?:\./)?/?games/([a-z0-9-]+)/?',path)
                    if hit:catalogue.setdefault(hit[1],{'id':hit[1],'title':hit[1].replace('-',' ').title(),'page_url':'https://www.peterandsonsgames.com/games/'+hit[1],'classification':'unknown','status':'pending','title_source':'slug_pending_metadata'})
            if url.hostname=='demo.spinart.cloud' and req['method']=='POST':
                api.append({'har_entry':index,'started_at':entry.get('startedDateTime'),'path':url.path,
                            'request':clean(parse(req.get('postData',{}).get('text',''))),
                            'http_status':entry['response']['status'],'response':clean(parse(text))})
            if url.hostname in ('peterandsons.org','cdn-demo.spinart.cloud') and (url.path.endswith('/launcher.js') or url.path.endswith('/launcher.html') or url.path.endswith('/config.json') or url.path.endswith('/version.json')):
                name=url.path.strip('/').replace('/','__')
                p=ROOT/'private/references'/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(text,encoding='utf8')
        inventory={'source':source.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'entries':len(entries),
                   'provider_api_counts':dict(Counter(e['path'] for e in api)),
                   'websocket_entries':sum(bool(e.get('_webSocketMessages')) for e in entries)}
        inventories.append(inventory)
        if api:
            trace={'source':inventory,'operations':api}
            save('private/traces/'+source.stem+'.json',trace);traces.append(trace)
    save('results/har-inventory.json',inventories)
    save('results/catalogue.json',list(catalogue.values()))
    save('private/captured-api.json',traces)
    print(json.dumps({'har_files':len(inventories),'catalogue_links':len(catalogue),'captured_api_files':len(traces),
                      'api_operations':sum(len(t['operations']) for t in traces)},ensure_ascii=False))

if __name__=='__main__':main()
