"""Initialize the next archived native demo; never sends a paid game action."""
import json,subprocess,sys,re
from urllib.parse import urlencode,urlsplit,parse_qs
from har_probe import ROOT
from demo_transport import native_read
from catalog_network import durable
from prepare_next_game import archived_or_read

def main():
    native=sys.argv[1] if len(sys.argv)>1 else 'rp_236'
    if not re.fullmatch(r'rp_[0-9]+',native):raise ValueError('invalid_native_id')
    folder=ROOT/('private/live/'+native+'-preparation')
    run=subprocess.run(['node','--expose-internals','native_bundle.cjs',str(folder/'game-js.body.private')],cwd=ROOT,capture_output=True,text=True,check=True)
    binding=json.loads(run.stdout)
    game=next(g for g in json.loads((ROOT/'catalogs/official-links.json').read_text(encoding='utf8'))['games'] if g.get('native_identity')==native)
    q=parse_qs(urlsplit(game['public_demo_url']).query)
    if q['mode']!=['fun'] or q['server_url']!=['https://srv.prrpeu3.com'] or q['operator']!=['rubyplay.com']:raise ValueError('unreviewed_public_demo_contract')
    _,data=archived_or_read('https://srv.prrpeu3.com/init-session/demo?'+urlencode({'gamename':native,'operator':q['operator'][0],'mode':'fun','currency':q['currency'][0],'playerSession':''}),folder,'fresh-session',{'srv.prrpeu3.com'})
    session=json.loads(data)
    if session.get('status')!='success' or not session.get('sessionKey'):raise ValueError('fresh_demo_not_accepted')
    prior=folder/'native-init.journal.json'
    if prior.exists():_,raw=archived_or_read('https://srv.prrpeu3.com/gameserver/demo',folder,'native-init',{'srv.prrpeu3.com'})
    else:_,raw=native_read('https://srv.prrpeu3.com/gameserver/demo',folder,'native-init',{'srv.prrpeu3.com'},
        {'v_protocol':binding['protocol'],'v_math':binding['math'],'key':session['sessionKey'],'device_type':'desktop','funModeData':session['funModeData'],'action':'init'})
    init=json.loads(raw)
    if init.get('status')!='ok':raise ValueError('native_init_not_ok')
    durable(ROOT/('results/'+native+'-binding.json'),{**binding,'game':native,'state':'native_init_received_binary_validation_pending',
        'financial_requests':0,'declared_purchases':init['data'].get('buy_feature_configs',[]),'buy_feature_available':init['data'].get('buy_feature_available'), 'next_action':init['data']['next_action'],
        'source_file':'private/live/'+native+'-preparation/game-js.body.private'})
    print(json.dumps({'game':native,'init':'ok','math':binding['math'],'declared_purchases':init['data'].get('buy_feature_configs',[]),'financial_requests':0}))

if __name__=='__main__':main()
