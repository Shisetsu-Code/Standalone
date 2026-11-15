"""One public-demo root, native-minimum spin and its required continuations."""
import json,subprocess,sys
from har_probe import ROOT
from demo_transport import native_read
from catalog_network import durable

def main():
    folder=ROOT/'private/live/rp_222-preparation'
    for _ in range(1000):
        purchase='--purchase' in sys.argv
        subprocess.run(['node','--expose-internals','native_codec.cjs','--purchase' if purchase else '--normal'],cwd=ROOT,check=True,capture_output=True)
        plan=json.loads((folder/'next-request.private').read_text())
        if plan['state']=='complete':
            result=json.loads((ROOT/('results/first-purchase.json' if purchase else 'results/first-normal.json')).read_text())
            print(json.dumps({'game':result['game'],'state':'complete','requests':len(result['steps']),'wallet_matches':all(s['wallet_matches'] for s in result['steps'])}));return
        if (folder/(plan['key']+'.journal.json')).exists():raise RuntimeError('existing_request_no_replay')
        native_read('https://srv.prrpeu3.com/gameserver/demo',folder,plan['key'],{'srv.prrpeu3.com'},plan['payload'],plan)
    raise RuntimeError('continuation_limit_no_replay')

if __name__=='__main__':main()
