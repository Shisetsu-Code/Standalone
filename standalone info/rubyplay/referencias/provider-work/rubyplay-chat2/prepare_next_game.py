"""Archive one next official demo's launcher and exact native client sources."""
import hashlib,json,sys,re
from urllib.parse import urlsplit
from har_probe import ROOT
from demo_transport import native_read
from prepare_client import source_text
from catalog_dom import DOM
from catalog_network import durable

AFRICAN_CATS_CDN = 'static2.eu3cdn-83.servpavloro.com'
AFRICAN_CATS_SOURCES = {
    '/africancats/latest/static/js/init.js': '7172d17b74ee619fea7c576ce80644725e062f25ba5e11e09c413a741c8787e8',
    '/africancats/latest/static/js/game.js': 'cd94725c10fbd5a1c70313b64c5eacaa6d17c89d52ea745601c48de7133c9c50',
}

def archived_or_read(url,folder,key,hosts):
    prior=folder/(key+'.journal.json')
    if prior.exists():
        meta=json.loads(prior.read_text(encoding='utf8'))
        if meta.get('status')!=200:raise RuntimeError('prior_attempt_not_successful_no_replay')
        raw=(folder/(key+'.body.private')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('source_checkpoint_hash_changed')
        return meta,raw
    return native_read(url,folder,key,hosts)

def main(native=None, *, reviewed_cdn_paths=()):
    queue=json.loads((ROOT/'results/game-processing-queue.json').read_text(encoding='utf8'))
    if native is not None and not re.fullmatch(r'rp_[0-9]+',native):raise ValueError('invalid_native_id')
    game=next(g for g in queue['games'] if g.get('native_identity') and (g['native_identity']==native if native else g['processing_status']=='pending_native_protocol'))
    native=game['native_identity'];folder=ROOT/('private/live/'+native+'-preparation')
    meta,raw=archived_or_read(game['public_demo_url'],folder,'launcher',{'prrpeu3.com'})
    assets=[]
    for node in DOM(raw.decode('utf8')).root.walk():
        value=node.attrs.get('src','');u=urlsplit(value)
        if node.tag!='script' or not u.path.endswith(('/static/js/init.js','/static/js/game.js')):continue
        expected_hash = None
        if native == 'rp_47' and u.netloc == AFRICAN_CATS_CDN:
            expected_hash = AFRICAN_CATS_SOURCES.get(u.path)
        migrated_asset = u.netloc == AFRICAN_CATS_CDN and u.path in reviewed_cdn_paths
        if u.scheme != 'https' or (u.netloc != 'static2.eu3cdn-82.linkmavqeno.com' and not expected_hash and not migrated_asset):
            raise ValueError('client_owner_requires_review')
        key='init-js' if u.path.endswith('/init.js') else 'game-js'
        info,data=archived_or_read(value,folder,key,{u.hostname})
        decoded=source_text(data)
        if expected_hash and hashlib.sha256(decoded.encode()).hexdigest() != expected_hash:
            raise ValueError('african_cats_client_source_changed')
        assets.append({'key':key,'url':value,'wire_sha256':info['sha256'],'decoded_sha256':hashlib.sha256(decoded.encode()).hexdigest(),'decoded_bytes':len(decoded.encode())})
    if len(assets)!=2:raise ValueError('native_client_layout_changed')
    durable(ROOT/('results/'+native+'-preparation.json'),{'game':native,'title':game['title'],'source_key':game['source_key'],
        'status':'sources_archived_native_binding_pending','assets':assets,'financial_requests':0})
    print(json.dumps({'game':native,'assets':len(assets),'financial_requests':0}))

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else None)
