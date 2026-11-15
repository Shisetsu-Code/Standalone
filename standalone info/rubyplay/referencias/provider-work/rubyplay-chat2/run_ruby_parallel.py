"""Three isolated demo sessions in parallel, adopting an existing game worker."""
import json,os,sys,time,threading,subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from har_probe import ROOT
from worker_lock import worker_lock
from catalog_network import durable

GAMES=('rp_65','rp_57','rp_37','rp_26','rp_29')
GUARD=threading.Lock()
PROGRESS={'pid':os.getpid(),'state':'running','mode':'parallel','max_concurrency':3,'games':{}}
def read(path):return json.loads(path.read_text(encoding='utf8'))
def stamp():return datetime.now(timezone.utc).isoformat()
def launch_candidates(states):return [game for game,state in states.items() if state=='pending']
def event(game,kind,**data):
    with GUARD:
        with (ROOT/'results/ruby-events.jsonl').open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'time':stamp(),'game':game,'event':kind,**data})+'\n');stream.flush();os.fsync(stream.fileno())
def status(game,value,**data):
    with GUARD:
        PROGRESS['games'][game]=value;PROGRESS.setdefault('details',{})[game]=data
        PROGRESS['updated_at']=stamp();durable(ROOT/'results/ruby-purchases-progress.json',PROGRESS)
def locked(game):
    try:
        with worker_lock(game):pass
        return False
    except RuntimeError:return True
def completed(game):
    path=ROOT/('results/'+game+'-ruby-purchase.json')
    return path.exists() and read(path).get('finished') and all(s['wallet_matches'] for s in read(path)['steps'])
def latest(game):
    paths=list((ROOT/'results').glob(game+'-ruby-probe-*.json'))
    if not paths:return 0,None
    path=max(paths,key=lambda p:int(p.stem.split('-')[-1]));return int(path.stem.split('-')[-1]),read(path)['ruby']
def save_purchase(game):
    result=read(ROOT/('results/'+game+'-ruby-purchase.json'));count,ruby=latest(game)
    folder=ROOT/('private/live/'+game+'-preparation')
    first=read(folder/(result['steps'][0]['key']+'.journal.json'));last=read(folder/(result['steps'][-1]['key']+'.journal.json'))
    info={'accumulation_spins':count,'ruby_before_purchase':ruby['balance'],'ruby_cost':ruby['needed'],
          'ruby_after_bonus':result['ruby']['balance'],'cash_cost':sum(s['cost'] for s in result['steps']),
          'cash_win':sum(s['paid_win'] for s in result['steps']),'purchase_responses':len(result['steps']),
          'purchase_started_at':first['started_at'],'purchase_closed_at':last['finished_at'],'all_wallet_checks_passed':True}
    status(game,'purchase_verified',**info);event(game,'purchase_verified',**info)
def run_game(game,adopt):
    child=None
    try:
        event(game,'existing_worker_adopted' if adopt else 'worker_start')
        if not adopt:
            root=ROOT/('results/'+game+'-root-state.json')
            if root.exists() and read(root)['state']!='closed':raise RuntimeError('stopped_active_root_needs_review')
            validated=subprocess.run(['node','--expose-internals','validate_next_init.cjs',game],cwd=ROOT,capture_output=True)
            if validated.returncode:raise RuntimeError('binary_init_failed')
            output=(ROOT/('private/ruby-parallel-'+game+'.log')).open('ab')
            child=subprocess.Popen([sys.executable,'-B','-u','run_next_normal.py',game,'--ruby-probe','--ruby-buy'],cwd=ROOT,stdout=output,stderr=output)
            output.close()
        last_ruby=None
        while True:
            if completed(game):save_purchase(game);return
            count,ruby=latest(game)
            status(game,'accumulating',normal_count=count,ruby=ruby,worker_pid=child.pid if child else 'adopted')
            if ruby is not None and ruby['balance']!=last_ruby:
                event(game,'ruby_balance_changed',normal_count=count,**ruby);last_ruby=ruby['balance']
            if child is not None and child.poll() is not None:raise RuntimeError('worker_stopped_before_purchase')
            if adopt and not locked(game):
                if completed(game):save_purchase(game);return
                raise RuntimeError('adopted_worker_stopped_before_purchase')
            time.sleep(5)
    except Exception as error:
        status(game,'needs_review',reason=str(error));event(game,'worker_needs_review',reason=str(error))
def main():
    states={game:'purchase_verified' if completed(game) else 'active' if locked(game) else 'pending' for game in GAMES}
    for game,state in states.items():status(game,state)
    for game,state in states.items():
        if state=='purchase_verified':save_purchase(game)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures=[executor.submit(run_game,g,states[g]=='active') for g in GAMES if states[g] in ('active','pending')]
        for future in futures:future.result()
    PROGRESS['state']='complete' if all(v=='purchase_verified' for v in PROGRESS['games'].values()) else 'stopped_needs_review'
    PROGRESS['finished_at']=stamp();durable(ROOT/'results/ruby-purchases-progress.json',PROGRESS)
    durable(ROOT/'results/ruby-future-considerations.json',{'event_log':'results/ruby-events.jsonl','cases':PROGRESS['details'],
        'lessons':['Zero initial Ruby does not mean unavailable: playing accumulates coins.',
                   'Record the actual coin threshold and normal-spin count per native game.',
                   'Run independent sessions concurrently; keep requests sequential within each game.',
                   'Stop on uncertain responses and preserve request journals; never replay them.',
                   'Reconcile cash and Ruby separately and close all bonus continuations.']})
if __name__=='__main__':
    with worker_lock('ruby-cases'):main()
