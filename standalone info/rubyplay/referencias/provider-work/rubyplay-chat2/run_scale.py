"""Scale test: one fresh public fun session per game, rounds at several bets.
Reuses demo_transport/native_read (journals, no-replay). >=0.7 s between requests;
stops on any non-200 / 403 / 429 / 503. Usage: run_scale.py rp_222 normal:1,buy:1,..."""
import json,subprocess,sys,re,os,time
from urllib.parse import urlencode,urlsplit,parse_qs
from har_probe import ROOT
from demo_transport import native_read
from catalog_network import durable
from worker_lock import worker_lock
from prepare_next_game import archived_or_read

def open_session(native):
    folder=ROOT/('private/live/'+native+'-preparation')
    binding=json.loads(subprocess.run(['node','--expose-internals','native_bundle.cjs',str(folder/'game-js.body.private')],cwd=ROOT,capture_output=True,text=True,check=True).stdout)
    game=next(g for g in json.loads((ROOT/'catalogs/official-links.json').read_text(encoding='utf8'))['games'] if g.get('native_identity')==native)
    q=parse_qs(urlsplit(game['public_demo_url']).query)
    if q['mode']!=['fun'] or q['server_url']!=['https://srv.prrpeu3.com'] or q['operator']!=['rubyplay.com']:raise ValueError('not_fun_mode')
    new=not (folder/'sc-fresh-session.journal.json').exists()
    _,data=archived_or_read('https://srv.prrpeu3.com/init-session/demo?'+urlencode({'gamename':native,'operator':q['operator'][0],'mode':'fun','currency':q['currency'][0],'playerSession':''}),folder,'sc-fresh-session',{'srv.prrpeu3.com'})
    if new:time.sleep(0.8)
    session=json.loads(data)
    if session.get('status')!='success' or not session.get('sessionKey'):raise ValueError('fresh_demo_not_accepted')
    if (folder/'sc-native-init.journal.json').exists():_,raw=archived_or_read('https://srv.prrpeu3.com/gameserver/demo',folder,'sc-native-init',{'srv.prrpeu3.com'})
    else:_,raw=native_read('https://srv.prrpeu3.com/gameserver/demo',folder,'sc-native-init',{'srv.prrpeu3.com'},{'v_protocol':binding['protocol'],'v_math':binding['math'],'key':session['sessionKey'],'device_type':'desktop','funModeData':session['funModeData'],'action':'init'});time.sleep(0.8)
    init=json.loads(raw)
    if init.get('status')!='ok':raise ValueError('native_init_not_ok')
    d=init['data'];return {'mode':q['mode'][0],'balance':d['player']['balance'],'currency':d['player']['currency'],'subunit':d['player']['subunit'],'bets':d['game_config']['bets'],'buy':d.get('buy_feature_configs')}

def main():
    native,plan=sys.argv[1],sys.argv[2]
    if not re.fullmatch(r'rp_[0-9]+',native):raise ValueError('bad id')
    folder=ROOT/('private/live/'+native+'-preparation')
    info=open_session(native)
    print(json.dumps({k:info[k] for k in ('mode','balance','currency','subunit','buy')}),flush=True)
    durable(ROOT/('results/'+native+'-scale-session.json'),info)
    cmd=['node','--expose-internals','plan_scale.cjs',native,'--stream','--all','--plan',plan]
    with subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8') as child:
        try:
            for _ in range(3000):
                line=child.stdout.readline()
                if not line:raise RuntimeError('decoder_stopped '+child.stderr.read()[-600:])
                event=json.loads(line);p=json.loads((folder/'next-request.private').read_text(encoding='utf8'))
                if event['state']=='complete' and p['state']=='complete':
                    child.stdin.close();child.wait(timeout=10);print('COMPLETE');return
                if event.get('key')!=p.get('key') or p.get('state')!='ready':raise RuntimeError('plan_mismatch')
                if (folder/(p['key']+'.journal.json')).exists():raise RuntimeError('prior_request_no_replay')
                time.sleep(0.8)
                res,_=native_read('https://srv.prrpeu3.com/gameserver/demo',folder,p['key'],{'srv.prrpeu3.com'},p['payload'],p)
                if res['status']!=200:raise RuntimeError('http_%s_stop_no_retry'%res['status'])
                child.stdin.write('response_archived\n');child.stdin.flush()
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=10)

if __name__=='__main__':
    with worker_lock(sys.argv[1]):main()
