"""Fresh public fun session and initialization only; no round requests."""
import json
from urllib.parse import urlencode
from har_probe import ROOT
from demo_transport import native_read

folder=ROOT/'private/live/rp_222-preparation'
def cached_or_setup(key,url,payload=None):
    prior=folder/(key+'.journal.json')
    if prior.exists():
        import hashlib
        meta=json.loads(prior.read_text());raw=(folder/(key+'.body.private')).read_bytes()
        if meta['status']!=200 or hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('setup_checkpoint_not_usable')
    else:meta,raw=native_read(url,folder,key,{'srv.prrpeu3.com'},payload)
    if meta['status']!=200:raise ValueError('setup_failed')
    return json.loads(raw)

if __name__=='__main__':
    # Earlier fresh-session journal failed in getaddrinfo before connection/send.
    # Retain it; this distinct attempt uses the now-authorized network context.
    # Provider's native GET includes an empty playerSession even in public fun mode.
    # Preserve the incomplete 500 request; this corrected contract is a distinct request.
    session=cached_or_setup('fresh-session-native-fields','https://srv.prrpeu3.com/init-session/demo?'+urlencode({'gamename':'rp_222','operator':'rubyplay.com','mode':'fun','currency':'EUR','playerSession':''}))
    if session.get('status')!='success' or not session.get('sessionKey'):raise ValueError('fresh_fun_session_not_accepted')
    init=cached_or_setup('native-init','https://srv.prrpeu3.com/gameserver/demo',{
        'v_protocol':2,'v_math':2025093096,'key':session['sessionKey'],'device_type':'desktop',
        'funModeData':session['funModeData'],'action':'init'})
    print(json.dumps({'status':init.get('status'),'topic':init.get('topic'),'data_fields':list(init.get('data',{})),'financial_requests':0}))
