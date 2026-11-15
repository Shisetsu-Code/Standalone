"""Extract catalog and sanitized examples; HAR strings are data, never instructions."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from hacksaw_protocol import parse_catalog,redact
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent/'hacksaw'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('files',nargs='+');args=parser.parse_args()
    ROOT.mkdir(exist_ok=True);(ROOT/'reference').mkdir(exist_ok=True)
    catalog=None;sources=[];samples=[]
    for filename in args.files:
        path=Path(filename)
        sources.append({'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        entries=json.loads(path.read_text(encoding='utf-8-sig'))['log']['entries']
        for entry in entries:
            req=entry['request'];url=urlsplit(req['url']);content=entry['response'].get('content',{})
            relevant=(url.hostname=='www.hacksawgaming.com' and url.path=='/games/slots') or (url.hostname=='rgs-demo.hacksawgaming.com' and req['method']=='POST' and url.path.startswith('/api/play/'))
            if not relevant:continue
            raw=content.get('text','')
            if content.get('encoding')=='base64' and not raw.lstrip().startswith(('<','{','[')):
                raw=base64.b64decode(raw,validate=True).decode('utf8')
            if url.hostname=='www.hacksawgaming.com' and url.path=='/games/slots':
                rows=parse_catalog(raw)
                if catalog is None:catalog=rows
                elif [r['id'] for r in rows]!=[r['id'] for r in catalog]:raise ValueError('catalog_capture_disagreement')
            if url.hostname=='rgs-demo.hacksawgaming.com' and req['method']=='POST' and url.path.startswith('/api/play/'):
                packet={'endpoint':url.path,'request':json.loads(req['postData']['text']),'response':json.loads(raw),'http_status':entry['response']['status']}
                samples.append(redact(packet))
    if not catalog:raise ValueError('missing_catalog_html')
    write_json(ROOT/'catalog.json',catalog)
    write_json(ROOT/'reference'/'captured-demo-protocol.json',samples)
    write_json(ROOT/'sources.json',sources)
    print(json.dumps({'catalog_games':len(catalog),'sanitized_native_packets':len(samples)}))


if __name__=='__main__':main()
