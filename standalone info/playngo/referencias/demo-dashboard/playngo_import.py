"""Public catalog and client references from supplied Play'n GO HARs."""
import base64,hashlib,json,re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
from bs4 import BeautifulSoup
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent
def content(entry):
    c=entry['response'].get('content',{});text=c.get('text','')
    return base64.b64decode(text).decode('utf8') if c.get('encoding')=='base64' else text

def main():
    out=ROOT/'playngo';(out/'reference').mkdir(parents=True,exist_ok=True);private=ROOT.parent/'playngo-private';private.mkdir(exist_ok=True)
    sources=[];catalog={};gids={};pages={}
    paths=sorted((Path.home()/'Desktop').glob('www.playngo.com_Archive [[]26-10-28*.har'))
    for path in paths:
        data=path.read_bytes();entries=json.loads(data)['log']['entries'];sources.append({'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),'entries':len(entries)})
        for entry in entries:
            url=urlsplit(entry['request']['url']);mime=entry['response'].get('content',{}).get('mimeType','')
            if path.name.endswith('12-59-02].har') and url.hostname=='www.playngo.com' and url.path=='/api/games':
                document=json.loads(content(entry));offset=int(parse_qs(url.query)['offset'][0]);pages[offset]=document
                for game in document['games']:catalog[game['sku']]=game
            if url.hostname=='www.playngo.com' and (mime.startswith('text/html') or mime=='text/x-component'):
                text=content(entry)
                if url.path=='/games' and mime.startswith('text/html'):
                    (private/'catalog-public.html').write_text(text,encoding='utf8')
                    for script in BeautifulSoup(text,'html.parser').find_all('script'):
                        raw=script.text
                        for match in re.finditer(r'self\.__next_f\.push\((\[.*\])\)',raw):
                            try:flight=json.loads(match[1])[1]
                            except (ValueError,IndexError):continue
                            m=re.search(r'"initialPage":(\{"games":\[)',flight)
                            if m:
                                page=json.JSONDecoder().raw_decode(flight[m.start(1):])[0];pages[0]=page
                                for game in page['games']:catalog[game['sku']]=game
                if url.path.startswith('/games/'):
                    cleaned=text.replace('\\u0026','&').replace('&amp;','&')
                    match=re.search(r'https://released\.playngonetwork\.com/casino/ContainerLauncher\?[^"<>\\\s]+',cleaned)
                    if match:
                        q=parse_qs(urlsplit(match[0]).query)
                        if q.get('pid')==['2'] and q.get('practice')==['1'] and q.get('demo')==['2']:gids[unquote(url.path.split('/')[-1])]=q['gid'][0]
            if url.hostname=='cdn.playngonetwork.com' and url.path.endswith('.js') and ('bundle' in url.path):
                text=content(entry);filename='launcher.js' if 'container-launcher' in url.path else url.path.split('/')[-1]
                if not (out/'reference'/filename).exists():(out/'reference'/filename).write_text(text,encoding='utf8')
    ordered=[];seen=set()
    for offset,page in sorted(pages.items()):
        for game in page['games']:
            if game['sku'] in seen:continue
            seen.add(game['sku']);slug=game['slug'];ordered.append({'ordinal':len(ordered)+1,'id':game['sku'],'slug':slug,'case_slug':re.sub('[^a-z0-9-]','',slug),'name':game['title'],'release_date':game.get('networkReleaseDate'),'details_url':'https://www.playngo.com/games/'+slug,'gid':gids.get(slug)})
    write_json(out/'catalog.json',ordered);write_json(out/'sources.json',{'sources':sources,'catalog_count':len(ordered),'page_metadata':{str(o):{k:v for k,v in p.items() if k!='games'} for o,p in pages.items()},'captured_launches':len(gids)})
    print(json.dumps({'catalog':len(ordered),'mapped_launches':sum(bool(g['gid']) for g in ordered),'first':ordered[:3],'metadata':{str(o):{k:v for k,v in p.items() if k!='games'} for o,p in list(pages.items())[:2]}},ensure_ascii=True))

if __name__=='__main__':main()
