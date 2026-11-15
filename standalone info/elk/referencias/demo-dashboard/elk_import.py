"""Import public ELK catalog; HARs are evidence, never transport credentials."""
import hashlib,json,re
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from bs4 import BeautifulSoup
from endorphina_run import write_json
from elk_protocol import redact_xml

ROOT=Path(__file__).resolve().parent

def catalog_from_html(html):
    soup=BeautifulSoup(html,'html.parser');found={}
    for a in soup.select('a[href]'):
        url=a['href']
        if not re.fullmatch(r'https://www\.elk-studios\.com/games/[a-z0-9-]+/',url) or url in found:continue
        parent=a.parent;launch=None
        while parent and not launch:
            launch=parent.select_one('a[data-src*="contentmedia.eu"]')
            if not launch:parent=parent.parent
        if not launch:raise ValueError('no_demo:'+url)
        query=parse_qs(urlparse(launch['data-src']).query)
        if query.get('mode')!=['demo'] or query.get('operatorid')!=['44']:raise ValueError('unexpected_demo')
        art=a
        while art.parent and not art.find('img',alt=True):art=art.parent
        image=art.find('img',alt=True);name=image['alt'].strip() if image else url.split('/')[-2]
        found[url]={'ordinal':len(found)+1,'id':query['gameid'][0],'slug':url.split('/')[-2],'name':name,'details_url':url,'xdm':query.get('xdm',['0'])[0]}
        if urlparse(launch['data-src']).hostname=='static-stage.contentmedia.eu':found[url]['direct_name']=query['gamename'][0]
    seen={}
    for game in found.values():
        if game['id'] in seen:game['shared_demo_with']=seen[game['id']]
        else:seen[game['id']]=game['slug']
    return list(found.values())

def main():
    out=ROOT/'elk';out.mkdir(exist_ok=True);(out/'reference').mkdir(exist_ok=True)
    games=catalog_from_html((ROOT.parent/'elk-private/catalog-public.html').read_text(encoding='utf8'))
    write_json(out/'catalog.json',games)
    sources=[]
    paths=[Path.home()/'Desktop'/name for name in ['www.elk-studios.com_Archive [26-10-28 11-51-34].har','static-stage.contentmedia.eu_Archive [26-10-28 11-54-19].har','www.elk-studios.com_Archive [26-10-28 11-55-57].har','www.elk-studios.com_Archive [26-10-28 11-57-13].har']]
    for i,path in enumerate(paths):
        data=path.read_bytes();document=json.loads(data);counts={}
        for entry in document['log']['entries']:
            url=entry['request']['url'];m=re.search(r'/capi/(\d+)/play/(init|purchase|checkwin)',url)
            if not m:continue
            key=m[1]+'-'+m[2];counts[key]=counts.get(key,0)+1
            content=entry['response'].get('content',{});body=content.get('text','')
            if content.get('encoding')=='base64':
                import base64
                body=base64.b64decode(body).decode('utf8')
            fixture=out/'reference'/(key+'.xml')
            if body and not fixture.exists():fixture.write_text(redact_xml(body),encoding='utf8')
        sources.append({'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),'native_messages':counts})
    write_json(out/'sources.json',{'catalog_count':len(games),'sources':sources,'policy':'Only public demo metadata imported; captured sessions are not reused.'})
    print(json.dumps({'catalog':len(games),'first':games[:3]},ensure_ascii=True))

if __name__=='__main__':main()
