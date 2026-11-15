"""Offline HAR evidence extraction. HAR identities never leave this process."""
import base64,hashlib,json,re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
ROOT=Path(__file__).resolve().parent.parent
FILES=['thunderspin.com_Archive [26-11-02 02-14-27].har','thunderspin.com_Archive [26-11-02 02-16-22].har']
def clean(x):
    if isinstance(x,dict):return {k:('[REDACTED]' if re.search(r'^(sid|sessionid|token|cookie|authorization|userid|secret|password)$',k,re.I) else clean(v)) for k,v in x.items()}
    if isinstance(x,list):return [clean(v) for v in x]
    return x
def main():
    sources=[];packets=[]
    for name in FILES:
        p=Path('C:/Users/Shisetsu/Desktop')/name;raw=p.read_bytes();h=json.loads(raw.decode('utf-8-sig'));game=None
        sources.append({'name':name,'sha256':hashlib.sha256(raw).hexdigest(),'entries':len(h['log']['entries'])})
        for ordinal,e in enumerate(h['log']['entries']):
            r=e['request'];u=urlsplit(r['url'])
            if not u.path.startswith('/service/'):continue
            q={k:v[-1] for k,v in parse_qs(r.get('postData',{}).get('text',''),keep_blank_values=True).items()}
            if 'slotcode' in q:game=q['slotcode']
            content=e['response'].get('content',{});t=content.get('text','');t=base64.b64decode(t).decode('utf-8') if content.get('encoding')=='base64' else t
            packets.append({'source_name':name,'entry_ordinal':ordinal,'game':game,'endpoint':u.path.rsplit('/',1)[-1],'host':u.hostname,'http_status':e['response']['status'],'session_fingerprint':hashlib.sha256(q.get('sid','').encode()).hexdigest()[:16],'request':clean(q),'response':clean(json.loads(t))})
    (ROOT/'private/captured-api.json').write_text(json.dumps(packets,indent=2),encoding='utf-8')
    (ROOT/'results/capture-sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    print({'sources':len(sources),'native_packets':len(packets)})
if __name__=='__main__':main()
