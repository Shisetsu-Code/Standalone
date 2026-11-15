"""One entry per verified public DEMO case. No retry of uncertain paid actions."""
import argparse,hashlib,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import unquote_plus,urlsplit
import requests
from endorphina_run import write_json
from playngo_client import Playngo
from playngo_rules import profile,continuation,latest,modes
from playngo_paths import batch_path,catalog_slice,selected_batch,BATCHES
ROOT=Path(__file__).resolve().parent
FOLDER=batch_path(selected_batch())

def read(path,default=None):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def public_bundle_targets(configuration,gid):
    root=configuration.get('resourceRoot','');parsed=urlsplit(root)
    if parsed.scheme!='https' or parsed.hostname!='cdn.playngonetwork.com' or parsed.query or parsed.fragment:return []
    game_path=urlsplit(configuration.get('gameURL','')).path.split('/')
    asset=game_path[-2] if len(game_path)>1 else gid
    names=list(dict.fromkeys([asset,gid]));return [root.rstrip('/')+'/games/'+name+'/'+name+'_desktop.bundle.js' for name in names if re.fullmatch('[a-z0-9]+',name or '')]

def baseline():
    path=FOLDER/'previous-providers-proof.json'
    if path.exists():return
    files=[]
    for provider in ('endorphina','hacksaw','nolimit','elk'):
        for folder in (ROOT/provider/'batches').glob('*'):
            for pattern in ('audit.json','rounds.json','catalog.json','purchases.json','risk.json'):
                p=folder/pattern
                if p.exists():files.append(p)
    files += [ROOT/p for p in ('catalog-complete.json','coverage-audit.json','purchases-audit.json') if (ROOT/p).exists()]
    for other in (ROOT/'playngo/batches').glob('*'):
        if other==FOLDER:continue
        files += [p for p in other.rglob('*.json') if p.name not in ('audit.json','inventory.json','previous-providers-proof.json')]
    write_json(path,{'sha256':{str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in files}})

def source_bundle(client,game):
    config=client.configuration
    # Only public CDN JavaScript. Never persist launcher/session configuration.
    urls=[]
    def visit(v):
        if isinstance(v,dict):
            for value in v.values():visit(value)
        elif isinstance(v,list):
            for value in v:visit(value)
        elif isinstance(v,str) and 'cdn.playngonetwork.com' in v:urls.append(v)
    visit(config)
    urls=public_bundle_targets(config,game['gid'])+urls
    candidates=[]
    for value in urls:
        candidates+=re.findall(r'https://cdn\.playngonetwork\.com/[^\s"<>]+',value)
    # gameURL is the public game's directory; desktop.bundle.js is loaded by its public launcher.
    for url in candidates:
        if '.bundle.js' in url:target=url.split('?')[0]
        else:
            parsed=urlsplit(url)
            if not parsed.path.endswith('/'):continue
            target=url.split('?')[0]+'desktop.bundle.js'
        parsed=urlsplit(target)
        if parsed.hostname!='cdn.playngonetwork.com' or not target.endswith('.bundle.js'):continue
        response=requests.get(target,timeout=45,allow_redirects=False)
        if response.status_code==200 and 'desktop_Entry' in response.text:
            path=ROOT/'playngo/reference'/f"{game['gid']}_desktop.bundle.js"
            path.write_bytes(response.content)
            return response.text,{'url':target,'sha256':digest(path),'file':str(path.relative_to(ROOT)).replace('\\','/')}
    raise ValueError('public_game_bundle_not_resolved')

def resolve(game):
    if game.get('gid'):return game
    response=requests.get(game['details_url'],timeout=45);response.raise_for_status()
    # A fresh official product page may publish its launcher GID.
    ids=set(re.findall(r'gid(?:=|%3D|\\u003d)([a-z0-9]+)',response.text,re.I))
    if len(ids)!=1:raise ValueError('official_gid_missing_or_ambiguous')
    game=dict(game,gid=next(iter(ids)));return game

def collect_correction_allowed(previous):
    steps=previous.get('trace',[])
    if len(steps)<2 or any(s.get('status')!='received' for s in steps):return False
    last=steps[-1]
    if last.get('commands')!=[{'code':2,'args':['6']}] or len(last.get('responses',[]))!=1 or last['responses'][0]['code']!=111:return False
    replies=steps[-2].get('responses',[])
    if not any(x['code']==2 and x['args'][:2]==['5','0'] for x in replies):return False
    try:return continuation([(x['code'],x['args']) for x in replies],0)=='4 0'
    except (ValueError,IndexError):return False

def run_game(original,execute=False,kind='normal',retry_rejected=False,retry_continuation=False):
    game=dict(original);case=game['case_slug']+'--'+kind
    path=FOLDER/'traces'/f'{case}.json'
    previous=read(path,{})
    if previous.get('summary',{}).get('status')=='unavailable':return previous['summary']
    rejected=False
    correcting_collect=retry_continuation and collect_correction_allowed(previous)
    if previous.get('summary',{}).get('entry_sent'):
        last=previous.get('trace',[{}])[-1]
        rejected=last.get('status')=='received' and len(last.get('responses',[]))==1 and last['responses'][0]['code']==111
        if not ((retry_rejected and rejected) or correcting_collect):return previous['summary']
    summary={'case':case,'id':game['id'],'slug':game['slug'],'name':game['name'],'kind':kind,'status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    if rejected:
        archive=FOLDER/'rejected'/(case+'--'+digest(path)[:16]+'.json');archive.parent.mkdir(exist_ok=True)
        if not archive.exists():write_json(archive,previous)
        doc['previous_attempts']=[{'file':str(archive.relative_to(FOLDER)).replace('\\','/'),'sha256':digest(archive),'reason':'Explicit native rejection; corrected parameter tuple requires a fresh DEMO session.'}]
        if correcting_collect:doc['previous_attempts'][0]['reason']='Explicit rejection of feature collect after needsCollect=false. Rule corrected to normal collect4 0; one fresh DEMO attempt.'
    def save(client):
        doc.update(authority=getattr(client,'authority',{}),trace=client.trace);write_json(path,doc)
    client=None
    try:
        game=resolve(game);doc['game']=game
        client=Playngo(game,save);client.bootstrap();client.connect()
        doc['public_bet_configuration']={key:client.configuration.get(key) for key in ('creditDisplay','defaultCreditDisplay','lines','defaultLimit','denom')}
        settings=client.configuration.get('settings','')
        rawsettings=settings.removeprefix('&settings=')
        initial=client.send('104 '+game['id']+' 0 %22'+rawsettings+'%22')
        if latest(initial,104)!=['1'] or latest(initial,109) is None:raise ValueError('game_initialization_incomplete')
        wallet=latest(initial,52)
        if not wallet or wallet[1]!='0':raise ValueError('fresh_demo_not_idle')
        source,proof=source_bundle(client,game)
        params=profile(source,initial,unquote_plus(rawsettings),doc['public_bet_configuration'])
        doc.update(profile=params,profile_proof=proof,settings_xml=unquote_plus(rawsettings))
        # Shared SDK strings are not proof of a published control.
        doc['mode_inventory']=modes(source,initial)
        if kind=='go-ultra':
            mode=doc['mode_inventory']
            if not mode['go_ultra']:raise ValueError('go_ultra_not_verified_or_disabled')
            from decimal import Decimal
            lines=Decimal(params['lines'])*Decimal(mode['factors'][0])
            if lines!=lines.to_integral_value():raise ValueError('boosted_lines_not_integer')
            params=dict(params,lines=int(lines),cost_native=int(lines)*params['coins']*params['denomination'])
            doc['profile']=params
        summary['status']='ready'
        if execute:
            if rejected:
                old=[s for s in previous['trace'] if any(x['code']==1 for x in s['commands'])][-1]['commands'][0]['args'][:3]
                if old==[str(params['coins']),str(params['lines']),str(params['denomination'])] and not correcting_collect:
                    write_json(path,previous)
                    return previous['summary']
            summary.update(entry_sent=True,status='running',balance_before_native=int(wallet[0]),cost_native=params['cost_native'])
            save(client) # A crash after this point must never automatically replay the entry.
            received=client.send('1 '+str(params['coins'])+' '+str(params['lines'])+' '+str(params['denomination'])+' 1')
            free_count=0;all_responses=list(received)
            for step in range(500):
                cmd=continuation(received,free_count)
                if cmd is None:break
                received=client.send(cmd);all_responses+=received
                if cmd.startswith('7 '):free_count+=1
            else:raise ValueError('internal_step_limit_reached')
            final=latest(received,52);end=latest(all_responses,3)
            if not final or final[1]!='0' or not end or int(end[3])!=0:raise ValueError('round_not_closed')
            win=int(end[2]);after=int(final[0]);before=summary['balance_before_native'];cost=params['cost_native']
            if before-cost+win!=after:raise ValueError('native_wallet_mismatch')
            summary.update(status='completed',balance_after_native=after,win_native=win,scale=params['scale'],internal_spin_results=sum(c==3 for c,a in all_responses),wallet_check='match')
        save(client)
    except Exception as exc:
        summary.update(status='needs_review',error=str(exc)[:300])
        disabled=next((x['args'][1] for step in (client.trace if client else []) for x in step.get('responses',[]) if x['code']==101 and len(x['args'])>1 and x['args'][1].startswith('Game not enabled.')),None)
        if disabled and not summary['entry_sent']:summary.update(status='unavailable',unavailable_reason=disabled)
        if client:save(client)
        else:write_json(path,doc)
    finally:
        if client:client.close()
    return summary

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=list(BATCHES),default=selected_batch());parser.add_argument('--execute',action='store_true');parser.add_argument('--limit',type=int,default=100);parser.add_argument('--start',type=int,default=1);parser.add_argument('--go-ultra',action='store_true');parser.add_argument('--retry-rejected',action='store_true');parser.add_argument('--retry-rejected-continuation',action='store_true');args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True);(FOLDER/'traces').mkdir(exist_ok=True);baseline()
    catalog=catalog_slice(args.batch);write_json(FOLDER/'catalog.json',catalog)
    selected=catalog[args.start-1:args.start-1+args.limit]
    results=[]
    # Sequential entries make uncertainties attributable and never flood the demo.
    for game in selected:
        kind='go-ultra' if args.go_ultra else 'normal'
        if args.go_ultra:
            normal=read(FOLDER/'traces'/f"{game['case_slug']}--normal.json",{})
            if not normal.get('mode_inventory',{}).get('go_ultra'):continue
        if args.retry_rejected or args.retry_rejected_continuation:
            previous=read(FOLDER/'traces'/f"{game['case_slug']}--normal.json",{})
            if not previous.get('summary',{}).get('entry_sent') or previous.get('summary',{}).get('status')=='completed':continue
        result=run_game(game,args.execute,kind,args.retry_rejected,args.retry_rejected_continuation);results.append(result)
        rows=[read(p)['summary'] for p in (FOLDER/'traces').glob('*.json') if read(p,{}).get('summary')]
        write_json(FOLDER/'rounds.json',rows)
        print(json.dumps({'ordinal':game['ordinal'],'game':game['name'],'status':result['status'],'error':result.get('error')},ensure_ascii=True),flush=True)
    return results
if __name__=='__main__':main()
