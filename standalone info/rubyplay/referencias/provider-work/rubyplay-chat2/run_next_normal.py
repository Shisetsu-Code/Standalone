"""Execute one bound public fun root; each send has a durable no-replay journal."""
import json,subprocess,sys,re,os
from har_probe import ROOT
from demo_transport import native_read
from catalog_network import durable
from worker_lock import worker_lock

def main():
    native=sys.argv[1] if len(sys.argv)>1 else 'rp_236'
    if not re.fullmatch(r'rp_[0-9]+',native):raise ValueError('invalid_native_id')
    folder=ROOT/('private/live/'+native+'-preparation')
    command=['node','--expose-internals','plan_next_normal.cjs',native,'--stream']+(['--all'] if '--all' in sys.argv else [])
    if '--ruby-probe' in sys.argv:command.append('--ruby-probe')
    if '--ruby-buy' in sys.argv:command.append('--ruby-buy')
    with subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8') as child:
        try:
            for _ in range(100000 if '--ruby-probe' in sys.argv else 1000):
                line=child.stdout.readline()
                if not line:
                    error=child.stderr.read()[-1000:]
                    raise RuntimeError('native_decoder_stopped; no retry; '+error)
                event=json.loads(line)
                plan=json.loads((folder/'next-request.private').read_text(encoding='utf8'))
                if event['state']=='complete' and plan['state']=='complete':
                    child.stdin.close();child.wait(timeout=10)
                    if child.returncode:raise RuntimeError('native_decoder_exit_failed')
                    durable(ROOT/('results/'+native+'-root-state.json'),{'game':native,'state':'closed','current_roots':[],'uncertain_roots':[]})
                    print(line.strip());return
                if event.get('key')!=plan.get('key') or plan.get('state')!='ready':raise RuntimeError('native_plan_event_mismatch')
                if (folder/(plan['key']+'.journal.json')).exists():raise RuntimeError('prior_request_no_replay')
                durable(ROOT/('results/'+native+'-root-state.json'),{'game':native,'state':'active','mode':plan.get('mode','normal'),'next_key':plan['key'],'pid':os.getpid(),'native_child_pid':child.pid,'uncertain_roots':[]})
                native_read('https://srv.prrpeu3.com/gameserver/demo',folder,plan['key'],{'srv.prrpeu3.com'},plan['payload'],plan)
                child.stdin.write('response_archived\n');child.stdin.flush()
            raise RuntimeError('continuation_limit')
        finally:
            if child.poll() is None:
                child.terminate();child.wait(timeout=10)

if __name__=='__main__':
    native=sys.argv[1] if len(sys.argv)>1 else 'rp_236'
    with worker_lock(native):main()
