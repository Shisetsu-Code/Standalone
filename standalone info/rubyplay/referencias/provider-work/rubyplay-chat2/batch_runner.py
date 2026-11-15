"""Resume official RubyPlay demos in batches; leave unsupported cases explicit."""
import argparse,hashlib,json,os,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from har_probe import ROOT
from catalog_network import durable
from worker_lock import worker_lock

GAME_HOSTS=('prrpeu3.com','srv.prrpeu3.com','static2.eu3cdn-82.linkmavqeno.com')
DEFERRED={'needs_adapter','needs_contract','needs_review'}

def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))

def select_candidates(games,states,revision,reviewed_families=None):
    candidates=[]
    for game in games:
        native=game.get('native_identity')
        if not native or not game.get('public_demo_url'):continue
        state=states.get(native,{})
        if state.get('state') in ('closed','setup_failed','access_blocked','uncertain'):continue
        if state.get('state')=='needs_contract' and reviewed_families is not None and state.get('client_class') not in reviewed_families:continue
        if state.get('state') in DEFERRED and state.get('revision')==revision:continue
        candidates.append(game)
    return sorted(candidates,key=lambda g:states.get(g['native_identity'],{}).get('state')!='active')

def check_game_hosts(root=ROOT):
    for host in GAME_HOSTS:
        if (root/'private/network'/(host+'.blocked.json')).exists():raise RuntimeError('provider_access_block_retained_'+host)

def check_financial_receipts(root=ROOT):
    for journal in (root/'private/live').glob('*/*.journal.json'):
        data=read(journal)
        if not data.get('financial_action'):continue
        key=journal.name.removesuffix('.journal.json');body=journal.with_name(key+'.body.private')
        if data.get('state')!='received' or data.get('status')!=200 or not body.exists():raise RuntimeError('uncertain_financial_request_'+journal.parent.name+'_'+key)
        raw=body.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=data.get('sha256'):raise RuntimeError('uncertain_financial_request_hash_'+key)
        try:accepted=json.loads(raw).get('status')=='ok'
        except ValueError:accepted=False
        if not accepted:raise RuntimeError('uncertain_financial_request_not_accepted_'+key)
    for claim in (root/'private/live').glob('*/*.claim'):
        if read(claim).get('financial_action') and not claim.with_name(claim.stem+'.journal.json').exists():raise RuntimeError('uncertain_financial_request_claim_without_journal')

def revision():
    digest=hashlib.sha256()
    for name in ('native_bundle.cjs','native_choices.cjs','native_contracts.json','validate_next_init.cjs','plan_next_normal.cjs'):
        digest.update(name.encode());digest.update((ROOT/name).read_bytes())
    return digest.hexdigest()

class StageFailure(RuntimeError):
    def __init__(self,stage,message):self.stage=stage;super().__init__(message)

def stage(command,name,native):
    run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace')
    folder=ROOT/'private/batch-logs';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(native+'.log')).open('a',encoding='utf8') as log:
        log.write('\n'+now()+' '+name+'\n'+run.stdout+'\n'+run.stderr)
    if run.returncode:
        # Detailed traces remain private. Public checkpoint contains only stage
        # and bounded native decoder diagnostics, never request bodies or keys.
        message='stage_failed_'+name
        if name=='binding':
            try:message=json.loads(run.stdout).get('error',message)[:350]
            except ValueError:pass
        raise StageFailure(name,message)
    return run.stdout

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=179);parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();rev=revision();games=read(ROOT/'catalogs/official-links.json')['games']
    progress_path=ROOT/'results/batch-progress.json'
    progress=read(progress_path) if progress_path.exists() else {'games':{}}
    states=progress['games']
    # Existing evidence, rather than an old batch cursor, determines completed work.
    live=read(ROOT/'results/live-summary.json') if (ROOT/'results/live-summary.json').exists() else {}
    for closed in live.get('completed_games',[]):
        if closed['game']=='rp_222' or closed.get('all_server_offered_purchase_modes_closed'):
            states[closed['game']]={'state':'closed','verified_modes':closed['modes'],'updated_at':now()}
    for path in (ROOT/'results').glob('rp_*-root-state.json'):
        root=read(path)
        if root['state']!='closed':states[root['game']]={'state':'active','updated_at':now()}
    contracts=read(ROOT/'native_contracts.json')
    candidates=select_candidates(games,states,rev,reviewed_families=set(contracts))[:max(0,args.limit)]
    if args.dry_run:
        print(json.dumps({'state':'dry_run','eligible_games':len(candidates),'already_closed':sum(s.get('state')=='closed' for s in states.values()),'first_games':[g['native_identity'] for g in candidates[:8]]}));return
    progress.update({'state':'running','pid':os.getpid(),'started_at':now(),'revision':rev,'current_game':None})
    def save():
        progress['updated_at']=now();progress['state_counts']=dict(Counter(s.get('state','pending') for s in states.values()))
        progress['unattempted_games']=sum(bool(g.get('native_identity')) and g['native_identity'] not in states for g in games)
        durable(progress_path,progress)
    def refresh():
        stage([sys.executable,'-B','checkpoint_live.py'],'checkpoint','summary')
        live=read(ROOT/'results/live-summary.json');report=read(ROOT/'results/provider-report.json')
        for key in ('status','verified_games','verified_modes','new_gameplay_requests_sent','current_roots','uncertain_roots'):
            report[key]=live[key]
        report.update({'updated_at':now(),'batch_state':progress['state'],
                       'batch_progress':'results/batch-progress.json','batch_pending':'results/batch-pending.json'})
        durable(ROOT/'results/provider-report.json',report)
        stage([sys.executable,'-B','finalize_evidence.py'],'manifest','summary')
    try:
        check_game_hosts();check_financial_receipts();save()
        for game in candidates:
            native=game['native_identity'];progress['current_game']=native
            # A received but not yet decoded root must be resumed before any
            # unrelated game. Unknown outcomes stop the whole batch above.
            states[native]={'state':'preparing','revision':rev,'title':game['title'],'updated_at':now()};save()
            try:
                check_game_hosts();check_financial_receipts()
                stage([sys.executable,'-B','prepare_next_game.py',native],'sources',native)
                meta=json.loads(stage(['node','--expose-internals','native_bundle.cjs',str(ROOT/('private/live/'+native+'-preparation/game-js.body.private'))],'binding',native))
                states[native].update({'client_class':meta['client_class'],'native_math':meta['math']})
                if meta['client_class'] not in contracts:
                    states[native].update({'state':'needs_contract','reason':'Native family not yet reviewed; no session or paid action sent.'});save();refresh();continue
                stage([sys.executable,'-B','open_next_session.py',native],'session',native)
                stage(['node','--expose-internals','validate_next_init.cjs',native],'binary_init',native)
                binding=read(ROOT/('results/'+native+'-binding.json'))
                if 'spin' not in binding.get('reviewed_transport_actions',[]):raise StageFailure('binary_init','native_spin_not_reviewed')
                states[native]['state']='processing';save()
                stage([sys.executable,'-B','run_next_normal.py',native,'--all'],'rounds',native)
                states[native].update({'state':'closed','updated_at':now()});save();refresh()
                print(json.dumps({'game':native,'state':'closed'}),flush=True)
            except StageFailure as error:
                check_game_hosts();check_financial_receipts()
                root_path=ROOT/('results/'+native+'-root-state.json')
                active=root_path.exists() and read(root_path).get('state')!='closed'
                state='needs_adapter' if error.stage=='binding' else ('needs_review' if error.stage in ('binary_init','rounds') else 'setup_failed')
                states[native].update({'state':state,'reason':str(error),'stage':error.stage,'updated_at':now()});save()
                if active:
                    progress['state']='halted_active_root_needs_offline_review';save();refresh();return
                refresh();print(json.dumps({'game':native,'state':state}),flush=True)
        progress.update({'state':'scan_finished','current_game':None,'finished_at':now()});save();refresh()
    except Exception as error:
        native=progress.get('current_game')
        if native in states:
            states[native].update({'state':'uncertain' if 'uncertain_financial_request' in str(error) else ('access_blocked' if 'provider_access_block_retained' in str(error) else 'needs_review'),'reason':str(error)[:400],'updated_at':now()})
        progress.update({'state':'halted','reason':str(error)[:400],'finished_at':now()});save()
        refresh();raise

if __name__=='__main__':
    with worker_lock('official-batch'):main()
