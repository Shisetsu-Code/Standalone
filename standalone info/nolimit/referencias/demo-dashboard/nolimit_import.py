"""Use captured catalog data only; never extract or reuse HAR authorization."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from endorphina_run import write_json
from nolimit_protocol import redact

ROOT=Path(__file__).resolve().parent/'nolimit'


def main():
    metadata={};released=None;upcoming={};sources=[]
    for path in sorted(Path('C:/Users/Shisetsu/Desktop').glob('nolimitcity*.har')):
        sources.append({'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for entry in json.loads(path.read_text(encoding='utf-8-sig'))['log']['entries']:
            url=urlsplit(entry['request']['url']);raw=entry['response'].get('content',{}).get('text','')
            if not raw or url.hostname not in ('cmsevo.com','nolimitcity.com'):continue
            if url.hostname=='cmsevo.com' and url.path=='/api/games':
                try:data=json.loads(raw)
                except ValueError:continue
                rows=data.get('data',[])
                if len(rows)==141:released=rows
                for row in rows:
                    attrs=row.get('attributes',{});code=attrs.get('tableId')
                    if code:metadata.setdefault(code,{}).update(attrs)
                    if code and attrs.get('isPresentable') is False:upcoming[code]=dict(attrs,id=row['id'])
            if '/_next/data/' in url.path and '/games/' in url.path:
                try:data=json.loads(raw)
                except ValueError:continue
                queries=data.get('pageProps',{}).get('initialState',{}).get('cmsApi',{}).get('queries',{})
                for query in queries.values():
                    attrs=query.get('data',{})
                    if isinstance(attrs,dict) and attrs.get('tableId'):metadata.setdefault(attrs['tableId'],{}).update(attrs)
    if not released:raise ValueError('complete_released_catalog_missing')
    result=[]
    for row in sorted(released,key=lambda r:int(r['id']),reverse=True):
        attrs=row['attributes'];code=attrs['tableId'];meta=metadata.get(code,{})
        result.append({'id':str(row['id']),'code':code,'name':attrs['name'],'slug':meta.get('slug',code),
            'details_url':'https://nolimitcity.com/games'+('/'+meta['slug'] if meta.get('slug') else ''),'release_date':meta.get('releaseDate')})
    if len({g['code'] for g in result})!=len(result):raise ValueError('duplicate_game_codes')
    ROOT.mkdir(exist_ok=True)
    write_json(ROOT/'catalog.json',result);write_json(ROOT/'sources.json',sources)
    write_json(ROOT/'upcoming.json',[{'code':code,'name':a['name'],'release_date':a.get('releaseDate')} for code,a in upcoming.items() if code not in {g['code'] for g in result}])
    private=ROOT.parent.parent/'nolimit-private'
    for source,dest in [('duck-fresh-init.json','DuckHunters2-init.json'),('duck-probe.json','DuckHunters2-diagnostic-round.json')]:
        write_json(ROOT/'reference'/dest,redact(json.loads((private/source).read_text(encoding='utf8'))))
    print(json.dumps({'released_games':len(result),'first':result[0]['name'],'hundredth':result[99]['name'],'upcoming':len(upcoming)}))


if __name__=='__main__':main()
