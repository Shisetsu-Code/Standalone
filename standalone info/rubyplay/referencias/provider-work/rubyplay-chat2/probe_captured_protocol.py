"""Inspect captured public demo client source offline; never replay a session."""
from pathlib import Path
import hashlib,json,re
from urllib.parse import urlsplit
from har_probe import ROOT,FILES,body,safe_url

def shape(value,depth=0):
    if depth>4:return type(value).__name__
    if isinstance(value,dict):return {k:shape(v,depth+1) for k,v in list(value.items())[:45]}
    if isinstance(value,list):return {'list_length':len(value),'first_item':shape(value[0],depth+1) if value else None}
    return type(value).__name__

def main():
    har=json.loads(FILES[0].read_text(encoding='utf-8-sig'));out=ROOT/'private/har-clients';out.mkdir(exist_ok=True)
    index=[]
    for i,e in enumerate(har['log']['entries']):
        req=e.get('request',{});u=urlsplit(req.get('url',''));mime=e.get('response',{}).get('content',{}).get('mimeType','')
        if u.hostname not in ('prrpeu3.com','srv.prrpeu3.com','static2.eu3cdn-82.linkmavqeno.com'):continue
        if 'javascript' in mime or u.path.endswith('.js'):
            raw=body(e);key=f'{i}-{hashlib.sha256(raw).hexdigest()[:12]}.js';(out/key).write_bytes(raw)
            row={'capture_entry':i,'url':safe_url(req['url']),'file':key,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
            index.append(row);print(json.dumps(row))
        if u.hostname=='srv.prrpeu3.com':
            raw=body(e);row={'capture_entry':i,'path':u.path,'method':req.get('method'),'status':e.get('response',{}).get('status'),'body_bytes':len(raw)}
            if raw:
                (out/f'{i}.response.private').write_bytes(raw)
                try:row['response_shape']=shape(json.loads(raw))
                except ValueError:row['response_type']='not_JSON'
            pd=req.get('postData',{});data=pd.get('text','')
            row['request_mime']=pd.get('mimeType');row['request_bytes']=len(data)
            if data:
                (out/f'{i}.request.private').write_text(data,encoding='utf8')
                try:row['request_shape']=shape(json.loads(data))
                except ValueError:row['request_type']='not_JSON'
            print(json.dumps(row))
    (out/'index.json').write_text(json.dumps(index,indent=2),encoding='utf8')

if __name__=='__main__':main()
