"""Archive exactly the client scripts referenced by a fresh public launcher."""
import hashlib,json,re,gzip,io
from urllib.parse import urlsplit
from har_probe import ROOT
from catalog_dom import DOM
from catalog_network import durable
from demo_transport import native_read

def source_text(data):
    if data.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:data=stream.read(20_000_001)
        if len(data)>20_000_000:raise ValueError('decoded_source_too_large')
    return data.decode('utf8')

def main():
    folder=ROOT/'private/live/rp_222-preparation'
    meta=json.loads((folder/'launcher.journal.json').read_text(encoding='utf8'))
    raw=(folder/'launcher.body.private').read_bytes()
    if meta['status']!=200 or hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('launcher_pin_mismatch')
    tree=DOM(raw.decode('utf8')).root;assets=[]
    for n in tree.walk():
        value=n.attrs.get('src','');u=urlsplit(value)
        if n.tag!='script' or not u.path.endswith(('/static/js/init.js','/static/js/game.js')):continue
        if u.scheme!='https' or u.hostname!='static2.eu3cdn-82.linkmavqeno.com':raise ValueError('client_source_owner_unreviewed')
        key='init-js' if u.path.endswith('/init.js') else 'game-js'
        prior=folder/(key+'.journal.json')
        if prior.exists():
            result=json.loads(prior.read_text(encoding='utf8'));data=(folder/(key+'.body.private')).read_bytes()
            if result['status']!=200 or hashlib.sha256(data).hexdigest()!=result['sha256']:raise ValueError('native_source_pin_changed')
        else:result,data=native_read(value,folder,key,{u.hostname})
        if result['status']!=200:raise RuntimeError('native_source_unavailable')
        decoded=source_text(data)
        assets.append({'key':key,'url':value,'sha256':result['sha256'],'bytes':len(data),
                       'decoded_sha256':hashlib.sha256(decoded.encode()).hexdigest(),'decoded_bytes':len(decoded.encode())})
    if len(assets)!=2:raise ValueError('native_source_layout_unrecognized')
    durable(ROOT/'results/client-preparation.json',{'game':'rp_222','source_key':'mad-hit-diamonds-extreme',
        'state':'native_sources_archived_protocol_binding_pending','launcher_http_status':meta['status'],
        'assets':assets,'new_financial_requests_sent':0,'transport':'isolated direct HTTP; existing relay 8793 was unavailable; no service started'})

if __name__=='__main__':main()
