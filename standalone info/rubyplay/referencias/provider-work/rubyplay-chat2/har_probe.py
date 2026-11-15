"""Offline HAR metadata; raw captured bodies stay in private/, never replayed."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent
FILES = [Path('C:/Users/Shisetsu/Desktop') / x for x in (
    'rubyplay.com_Archive [26-11-01 12-29-58].har',
    'slotcatalog.com_Archive [26-11-01 12-31-21].har',
    'slotcatalog.com_Archive [26-11-01 12-31-44].har')]

def body(entry):
    c=entry.get('response',{}).get('content',{})
    value=c.get('text','')
    return base64.b64decode(value) if c.get('encoding')=='base64' else value.encode('utf8')

def safe_url(url):
    u=urlsplit(url)
    path='/'.join('[dynamic]' if re.fullmatch(r'[a-fA-F0-9-]{28,}|[A-Za-z0-9_-]{60,}',s) else s for s in u.path.split('/'))
    q=[(k,v if k.lower() in ('page','paged','offset','limit','lang','locale','p') and re.fullmatch(r'[a-zA-Z0-9_-]{1,8}',v) else '[redacted]') for k,v in parse_qsl(u.query)]
    return u._replace(netloc=u.hostname or '',path=path,query=urlencode(q),fragment='').geturl()

def main():
    private=ROOT/'private'/'har-documents';private.mkdir(parents=True,exist_ok=True)
    results=[]
    for number,path in enumerate(FILES):
        raw=path.read_bytes();doc=json.loads(raw.decode('utf-8-sig'));es=doc.get('log',{}).get('entries',[])
        row={'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'entries':len(es),
             'hosts':dict(Counter(urlsplit(e.get('request',{}).get('url','')).hostname for e in es)),
             'websocket_messages':sum(len(e.get('_webSocketMessages',[])) for e in es),'documents':[],'json_routes':[]}
        for i,e in enumerate(es):
            url=e.get('request',{}).get('url','');u=urlsplit(url);c=e.get('response',{}).get('content',{});mime=c.get('mimeType','')
            if u.hostname in ('rubyplay.com','www.rubyplay.com','slotcatalog.com','www.slotcatalog.com') and ('html' in mime or 'json' in mime):
                data=body(e);suffix='.html' if 'html' in mime else '.json';out=private/f'{number}-{i}{suffix}'
                if data and not out.exists():out.write_bytes(data)
                info={'entry':i,'captured_at':e.get('startedDateTime'),'url':safe_url(url),'status':e.get('response',{}).get('status'),'mime':mime,'body_bytes':len(data),
                      'sha256':hashlib.sha256(data).hexdigest(),'private_file':str(out.relative_to(ROOT))}
                if 'json' in mime and data:
                    try:
                        j=json.loads(data);info['shape']=list(j)[:30] if isinstance(j,dict) else {'type':type(j).__name__,'length':len(j)}
                    except (ValueError,TypeError):pass
                row['documents'].append(info)
            elif 'json' in mime:
                row['json_routes'].append({'url':safe_url(url),'status':e.get('response',{}).get('status'),'body_bytes':c.get('size')})
        results.append(row)
    (ROOT/'har-index.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf8')
    for r in results:
        print(json.dumps({k:v for k,v in r.items() if k!='json_routes'},ensure_ascii=False))

if __name__=='__main__':main()
