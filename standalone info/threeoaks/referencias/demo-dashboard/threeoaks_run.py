"""Isolated first-100 inventory and durable single-entry public demo cases."""
import argparse,hashlib,json,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from threeoaks_client import ThreeOaks,PRIVATE,RateLimited,validated_state
from threeoaks_core import bet_profile,mode_inventory,next_action,reconcile,sanitize
from endorphina_run import write_json
from threeoaks_layout import batch_folder

ROOT=Path(__file__).resolve().parent
FOLDER=batch_folder()
def read(path,default=None):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def error_text(exc):return re.sub(r'[0-9a-f]{24,}','[REDACTED]',str(exc))[:300]

def baseline():
    path=FOLDER/'previous-providers-proof.json'
    if path.exists():return
    pinned={}
    for name in ['batches','endorphina','hacksaw','nolimit','elk','playngo','data/purchase-runs']:
        for f in (ROOT/name).rglob('*.json'):
            rel=f.relative_to(ROOT)
            if any(x in rel.parts for x in ['reference','local-assets','assets']) or f.name.startswith('reference-'):continue
            pinned[rel.as_posix()]=digest(f)
    for f in ROOT.glob('*.json'):pinned[f.name]=digest(f)
    if FOLDER.name!='1-100':
        previous=ROOT/'threeoaks/batches/1-100'
        for name in ['traces','initializations','partial-rounds','classification-corrections']:
            for f in (previous/name).rglob('*.json'):pinned[f.relative_to(ROOT).as_posix()]=digest(f)
        for name in ['catalog.json','rounds.json','inventory.json']:pinned[(previous/name).relative_to(ROOT).as_posix()]=digest(previous/name)
    write_json(path,{'provider':'threeoaks','sha256':pinned})

def inventory_game(game):
    path=FOLDER/'initializations'/(game['id']+'.json');previous=read(path,{})
    if previous.get('status')=='ready':
        proof=previous.get('source_proof',{});p=ROOT/proof.get('file','missing')
        if p.is_file() and digest(p)==proof.get('sha256'):return previous
    d={'game':game,'status':'running'}
    def save(c):d.update(authority=c.authority,trace=c.trace,launcher=c.launcher,start=sanitize(c.start),context=c.context);write_json(path,d)
    c=ThreeOaks(game,save)
    try:
        start=c.bootstrap();source,proof=c.source();d.update(status='ready',profile=bet_profile(start),source_proof=proof,modes=mode_inventory(start,source));save(c)
    except Exception as exc:d.update(status='needs_review',error=error_text(exc),rate_limited=isinstance(exc,RateLimited));save(c)
    finally:c.close()
    return d

def rebuild():
    rows=[read(p)['summary'] for p in (FOLDER/'traces').glob('*.json') if read(p,{}).get('summary')];write_json(FOLDER/'rounds.json',sorted(rows,key=lambda r:(r['ordinal'],r['key'])))
    inv=[read(FOLDER/'initializations'/(g['id']+'.json'),{'game':g,'status':'pending'}) for g in read(FOLDER/'catalog.json',[])];write_json(FOLDER/'inventory.json',inv)
    return rows

def can_replace_closed(doc):
    try:
        if doc.get('previous_attempts') or doc['summary']['status']!='needs_review' or not doc['summary']['entry_sent']:return False
        a=doc['authority']
        if not a.get('public_demo') or a.get('currency')!='FUN' or a.get('game_id')!=doc['game']['id']:return False
        trace=doc['trace'];last=trace[-1];req=last['request'];res=last.get('response',{})
        if last.get('status')!='rejected_native' or last.get('http_status')!=200 or res.get('status',{}).get('code')!='GAME_REOPENED' or res.get('request_id')!=req['request_id'] or res.get('command')!=req['command'] or req['command']!='play':return False
        state=validated_state(trace[:-1]);source_path=ROOT/doc['source_proof']['file']
        if digest(source_path)!=doc['source_proof']['sha256']:return False
        source=source_path.read_text(encoding='utf8')
        if req['action']!=next_action(state['context'],source):return False
        paid=[s for s in trace if s['request'].get('action',{}).get('name') in ('spin','buy_spin','booster_spin')]
        return len(paid)==1 and paid[0]['request']['action']==doc['mode']['action']
    except Exception:return False

def can_retry_rejected(doc):
    """Only the reviewed redundant-factor rejection; never an uncertain play."""
    try:
        if doc.get('previous_attempts') or doc['summary']['status']!='needs_review' or not doc['summary']['entry_sent']:return False
        trace=doc['trace'];last=trace[-1];req=last['request'];res=last.get('response',{})
        if last.get('status')!='rejected_native' or last.get('http_status')!=200 or res.get('status',{}).get('code')!='SERVER_ERROR' or req.get('command')!='play' or req.get('request_id')!=res.get('request_id') or res.get('command')!='play':return False
        state=validated_state(trace[:-1]);start=state['start'];context=res.get('context',{})
        if res.get('user',{}).get('currency')!='FUN' or res['user']['balance']!=start['user']['balance'] or context.get('round_finished') is not True or context.get('current')!='spins' or 'spin' not in context.get('actions',[]):return False
        if len([s for s in trace if s['request']['command']=='play'])!=1:return False
        a=doc['authority']
        if not a.get('public_demo') or a.get('currency')!='FUN' or a.get('game_id')!=doc['game']['id']:return False
        path=ROOT/doc['source_proof']['file']
        if digest(path)!=doc['source_proof']['sha256']:return False
        corrected=next(m for m in mode_inventory(start,path.read_text(encoding='utf8')) if m['key']==doc['summary']['key'])
        old=req['action'];params=dict(old['params']);factor=params.pop('bet_factor',None)
        return factor==bet_profile(start)['bet_factor'] and corrected.get('supported') and corrected['action']=={'name':old['name'],'params':params} and old==doc['mode']['action']
    except Exception:return False

def run_case(game,key,replace_closed=False,retry_rejected=False):
    case=game['id']+'--'+key;path=FOLDER/'traces'/(case+'.json');previous=read(path,{})
    corrected_retry=retry_rejected and can_retry_rejected(previous)
    replacing=(replace_closed and can_replace_closed(previous)) or corrected_retry
    if previous.get('summary',{}).get('entry_sent') and not replacing:return previous['summary']
    summary={'case':case,'id':game['id'],'ordinal':game['ordinal'],'name':game['name'],'key':key,'kind':'normal' if key=='normal' else 'purchase','status':'running','entry_sent':False}
    d={'game':game,'summary':summary}
    if previous.get('previous_attempts'):d['previous_attempts']=previous['previous_attempts']
    if replacing:
        archive=FOLDER/'partial-rounds'/(case+'--'+digest(path)[:16]+'.json');archive.parent.mkdir(exist_ok=True)
        if not archive.exists():write_json(archive,previous)
        d['previous_attempts']=[{'file':archive.relative_to(FOLDER).as_posix(),'sha256':digest(archive),'status':'rejected_before_debit' if corrected_retry else 'partial_session_closed_not_completed','reason':'Native SERVER_ERROR, unchanged FUN wallet and idle round. Retrying the source-verified request without the redundant bet_factor.' if corrected_retry else 'Original accepted round stopped for parser review. Provider explicitly returned GAME_REOPENED on its continuation. This is a separate fresh FUN demo replacement; original round is not claimed complete.'}]
    def save(c):d.update(authority=c.authority,trace=c.trace,launcher=c.launcher,start=sanitize(c.start));write_json(path,d)
    c=ThreeOaks(game,save,PRIVATE/(case+'.json'))
    try:
        start=c.bootstrap();source,proof=c.source();modes=mode_inventory(start,source);mode=next((m for m in modes if m['key']==key),None)
        if not mode or not mode.get('supported'):raise ValueError('mode_not_verified:'+str(mode.get('error') if mode else key))
        if mode['action']['name'] not in start['context']['actions']:raise ValueError('entry_action_not_currently_offered')
        before=start['user']['balance']
        if before<mode['cost_native']:raise ValueError('insufficient_fictional_demo_funds')
        d.update(profile=bet_profile(start),source_proof=proof,mode=mode,mode_inventory=modes)
        summary.update(entry_sent=True,kind=mode['kind'],cost_native=mode['cost_native'],scale=d['profile']['scale'],balance_before_native=before);c.checkpoint()
        offset=len(c.trace);c.play(mode['action'])
        for _ in range(2000):
            action=next_action(c.context,source)
            if action is None:break
            c.play(action)
        else:raise ValueError('internal_continuation_limit')
        result=reconcile(before,mode['cost_native'],c.trace[offset:],source);summary.update(result,status='completed');c.checkpoint()
    except Exception as exc:
        if not any(s['request']['command']=='play' for s in c.trace):summary['entry_sent']=False
        summary.update(status='needs_review',error=error_text(exc),rate_limited=isinstance(exc,RateLimited),transport_blocked=isinstance(exc,(IOError,ConnectionError)));c.checkpoint()
    finally:c.close()
    rebuild();return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--inventory',action='store_true');p.add_argument('--normals',action='store_true');p.add_argument('--modes',action='store_true');p.add_argument('--replace-closed',action='store_true');p.add_argument('--retry-rejected',action='store_true');p.add_argument('--start',type=int,default=1);p.add_argument('--limit',type=int,default=100);args=p.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    for name in ['traces','initializations']:(FOLDER/name).mkdir(exist_ok=True)
    baseline();games=[g for g in read(FOLDER/'catalog.json') if g['ordinal']>=args.start][:args.limit]
    if args.inventory:
        for g in games:
            d=inventory_game(g);print(json.dumps({'ordinal':d['game']['ordinal'],'name':d['game']['name'],'status':d['status'],'modes':len(d.get('modes',[])),'unsupported':sum(not m.get('supported') for m in d.get('modes',[])),'error':d.get('error')},ensure_ascii=True),flush=True)
            if d.get('rate_limited'):rebuild();return
        rebuild()
    for g in games:
        inv=read(FOLDER/'initializations'/(g['id']+'.json'),{})
        for mode in inv.get('modes',[]):
            if (mode['kind']=='normal' and args.normals) or (mode['kind']!='normal' and args.modes):
                if not mode.get('supported'):continue
                r=run_case(g,mode['key'],args.replace_closed,args.retry_rejected);print(json.dumps({'ordinal':g['ordinal'],'game':g['name'],'key':mode['key'],'status':r['status'],'error':r.get('error')},ensure_ascii=True),flush=True)
                if r.get('rate_limited') or r.get('transport_blocked'):return
if __name__=='__main__':main()
