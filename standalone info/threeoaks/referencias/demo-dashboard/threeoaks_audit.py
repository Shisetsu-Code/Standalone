"""Recompute every paid case and compare against the first-100 native inventory."""
import json
from threeoaks_run import ROOT,FOLDER,read,digest,can_replace_closed,can_retry_rejected
from threeoaks_core import bet_profile,mode_inventory,reconcile
from endorphina_run import write_json
from threeoaks_layout import batch_name,batch_games,catalog_matches

def verify_classification_correction(d):
    try:
        correction=d['classification_correction'];archive=(FOLDER/correction['file']).resolve()
        if not archive.is_relative_to((FOLDER/'classification-corrections').resolve()) or not archive.is_file() or digest(archive)!=correction['sha256']:return False
        old=read(archive);s=old['summary'];r=d['summary']
        if s.get('status')!='needs_review' or s.get('error')!='native_wallet_mismatch' or not s.get('entry_sent') or s['case']!=correction['from_case'] or s['case']==r['case']:return False
        if any(old.get(k)!=d.get(k) for k in ['trace','game','authority','start','source_proof','launcher','profile']):return False
        if old['mode']['action']!=d['mode']['action'] or s['cost_native']==d['mode']['cost_native'] or r['cost_native']!=d['mode']['cost_native']:return False
        proof=d['source_proof'];source=ROOT/proof['file']
        if digest(source)!=proof['sha256']:return False
        modes=mode_inventory(d['start'],source.read_text(encoding='utf8'))
        if next(m for m in modes if m['key']==r['key'])!=d['mode']:return False
        reconcile(d['start']['user']['balance'],d['mode']['cost_native'],[t for t in d['trace'] if t['request']['command']=='play'],source.read_text(encoding='utf8'))
        return True
    except Exception:return False

def verify_case(d):
    errors=[]
    try:
        g=d['game'];r=d['summary'];a=d['authority'];trace=d['trace'];proof=d['source_proof'];source=ROOT/proof['file']
        if a.get('provider')!='threeoaks' or a.get('public_demo') is not True or a.get('fresh_session') is not True or a.get('currency')!='FUN' or a.get('game_id')!=g['id'] or a.get('server_host')!='betman-demo.head.3oaks.com':raise ValueError('not_verified_official_fun_demo')
        if r['id']!=g['id'] or r['case']!=g['id']+'--'+r['key']:raise ValueError('case_identity_mismatch')
        if not source.is_file() or digest(source)!=proof['sha256'] or proof['url']!=d['launcher']['client_base']+'src/game.js':raise ValueError('stale_or_unbound_public_source')
        start=d['start'];profile=bet_profile(start)
        if profile!=d['profile']:raise ValueError('bet_profile_mismatch')
        modes=mode_inventory(start,source.read_text(encoding='utf8'));mode=next((m for m in modes if m['key']==r['key']),None)
        if not mode or not mode.get('supported') or mode!=d['mode']:raise ValueError('mode_not_independently_reproducible')
        gaming=[];started=False;starts=[]
        for step in trace:
            req=step['request'];res=step.get('response',{})
            if step.get('status')!='received' or step.get('http_status')!=200 or res.get('status',{}).get('code')!='OK':raise ValueError('uncertain_or_rejected_request')
            if req['request_id']!=res.get('request_id') or req['command']!=res.get('command'):raise ValueError('native_reply_identity_mismatch')
            for obj in (req,res):
                for key in ['token','session_id','huid']:
                    if obj.get(key) not in (None,'[REDACTED]'):raise ValueError('credential_not_redacted')
            if req['command']=='start':starts.append(res)
            if req['command']=='play':started=True;gaming.append(step)
            elif started:raise ValueError('unexpected_command_after_entry')
            elif req['command'] not in ('login','start'):raise ValueError('unexpected_pre_entry_command')
        if starts!=[start] or not gaming or gaming[0]['request']['action']!=mode['action']:raise ValueError('entry_or_initialization_mismatch')
        if mode['action']['name'] not in start['context'].get('actions',[]):raise ValueError('paid_action_not_offered')
        for key,value in mode['action']['params'].items():
            if gaming[0]['response']['context'].get('last_args',{}).get(key)!=value:raise ValueError('paid_parameter_echo_mismatch:'+key)
        result=reconcile(start['user']['balance'],mode['cost_native'],gaming,source.read_text(encoding='utf8'))
        if r.get('status')!='completed' or r.get('kind')!=mode['kind'] or r.get('scale')!=profile['scale'] or any(r.get(k)!=v for k,v in result.items()):raise ValueError('financial_summary_mismatch')
        for attempt in d.get('previous_attempts',[]):
            archive=FOLDER/attempt['file']
            status=attempt.get('status');valid=can_replace_closed if status=='partial_session_closed_not_completed' else can_retry_rejected if status=='rejected_before_debit' else None
            if not archive.is_file() or digest(archive)!=attempt['sha256'] or valid is None or not valid(read(archive)):raise ValueError('previous_attempt_not_preserved_or_not_safely_replaced')
        if d.get('classification_correction') and not verify_classification_correction(d):raise ValueError('accepted_round_reclassification_not_preserved')
    except Exception as exc:errors.append(str(exc))
    return errors

def audit(check_previous=True):
    catalog=read(FOLDER/'catalog.json',[]);rows=read(FOLDER/'rounds.json',[]);inventory=[];issues=[];pending=[];verified=[];expected=set();unavailable_modes=[];hashes={}
    for name in ['threeoaks_layout.py','threeoaks_core.py','threeoaks_client.py','threeoaks_browser_bridge.py','threeoaks_run.py','threeoaks_audit.py','threeoaks_reports.py','provider_reports.py','threeoaks/catalog.json','threeoaks/reference/serializer-bindings.json','threeoaks/reference/continuation-bindings.json','threeoaks/reference/gamerunner.client.js']:
        p=ROOT/name
        if p.exists():hashes[name]=digest(p)
    for name in ['catalog.json','rounds.json','inventory.json','previous-providers-proof.json','run-status.json']:
        p=FOLDER/name
        if p.exists():hashes[p.relative_to(ROOT).as_posix()]=digest(p)
    for game in catalog:
        path=FOLDER/'initializations'/(game['id']+'.json');d=read(path,{})
        if not path.exists() or d.get('status')!='ready':pending.append({'game':game['id'],'case':'inventory','reason':d.get('error','not_initialized')});continue
        hashes[path.relative_to(ROOT).as_posix()]=digest(path);proof=d['source_proof'];p=ROOT/proof['file']
        if not p.exists() or digest(p)!=proof['sha256']:issues.append({'game':game['id'],'errors':['stale_inventory_source']});continue
        hashes[proof['file']]=proof['sha256']
        try:modes=mode_inventory(d['start'],p.read_text(encoding='utf8'))
        except Exception as exc:issues.append({'game':game['id'],'errors':[str(exc)]});continue
        if modes!=d.get('modes'):issues.append({'game':game['id'],'errors':['stale_mode_inventory']})
        inventory.append({'id':game['id'],'ordinal':game['ordinal'],'name':game['name'],'modes':modes})
        for mode in modes:
            case=game['id']+'--'+mode['key']
            if mode.get('error')=='buy_price_or_action_unpublished':
                unavailable_modes.append({'id':game['id'],'key':mode['key'],'reason':'No native price/action published; not executed or claimed tested.'});continue
            expected.add(case)
            row=next((r for r in rows if r['case']==case),None)
            if row is None or row.get('status')!='completed':pending.append({'game':game['id'],'case':case,'reason':row.get('error',row['status']) if row else mode.get('error','not_executed')});continue
            trace_path=FOLDER/'traces'/(case+'.json');doc=read(trace_path);errors=verify_case(doc)
            if doc['summary']!=row:errors.append('round_index_mismatch')
            hashes[trace_path.relative_to(ROOT).as_posix()]=digest(trace_path)
            for attempt in doc.get('previous_attempts',[]):hashes[(FOLDER/attempt['file']).relative_to(ROOT).as_posix()]=attempt['sha256']
            if doc.get('classification_correction'):
                correction=doc['classification_correction'];hashes[(FOLDER/correction['file']).relative_to(ROOT).as_posix()]=correction['sha256']
            if errors:issues.append({'case':case,'errors':errors})
            else:verified.append(case)
    extras=[r['case'] for r in rows if r['case'] not in expected]
    if extras:issues.append({'case':'unexpected_cases','errors':extras})
    proof=read(FOLDER/'previous-providers-proof.json',{});pinned=proof.get('sha256',{});changed=[]
    if check_previous:
        changed=[name for name,sha in pinned.items() if not (ROOT/name).is_file() or digest(ROOT/name)!=sha]
        if len(pinned)<40:changed.append('[baseline_missing]')
        hashes.update(pinned)
    normal=sum(r['case'] in verified and r['kind']=='normal' for r in rows);buy=sum(r['case'] in verified and r['kind']=='buy' for r in rows);booster=sum(r['case'] in verified and r['kind']=='booster' for r in rows)
    expected_normal=len(batch_games())
    result={'provider':'threeoaks','batch':batch_name(),'catalog_total':len(read(ROOT/'threeoaks/catalog.json',[])),'expected_normal':expected_normal,'normal_cases':normal,'purchase_cases':buy,'booster_cases':booster,'verified_cases':len(verified),'verified_case_ids':sorted(verified),'expected_cases':len(expected),'unpriced_modes_not_executed':unavailable_modes,'pending_cases':pending,'problems':issues,'previous_providers_unchanged':check_previous and not changed,'previous_files':len(pinned),'changed_previous_files':changed,'passed':catalog_matches(catalog) and normal==expected_normal and set(verified)==expected and not issues and not pending and check_previous and not changed,'scope':'One normal entry and every currently available priced purchase/booster; native continuations separate. Excludes exhaustive natural outcomes and undefined unpriced options.','input_hashes':hashes}
    result['partial_attempts_not_completed']=[{'case':r['case'],'file':a['file']} for r in rows for a in read(FOLDER/'traces'/(r['case']+'.json'),{}).get('previous_attempts',[]) if a.get('status')=='partial_session_closed_not_completed']
    write_json(FOLDER/'audit.json',result);return result

if __name__=='__main__':
    r=audit();print(json.dumps({k:v for k,v in r.items() if k not in ('input_hashes','verified_case_ids')},ensure_ascii=True))
