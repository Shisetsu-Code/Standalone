"""Recompute closure, entry cost and wallet from sanitized native packets."""
import hashlib,json
from pathlib import Path
from playngo_run import ROOT,FOLDER,read,digest
from endorphina_run import write_json
from playngo_paths import BATCHES

def continuation_errors(trace):
    errors=[];previous=None;free_processed=0;started=False
    for step in trace:
        sent=step.get('commands',[])
        if not started:
            if any(x['code']==1 for x in sent):
                started=True
                if len(sent)!=1:errors.append('multiple_entry_commands')
            else:
                if any(x['code'] not in (103,101,104) for x in sent):errors.append('unexpected_pre_entry_command')
                continue
        elif previous is not None:
            if any(x['code']==52 and len(x['args'])>1 and x['args'][1]=='0' for x in previous):errors.append('action_after_native_closure')
            if len(sent)!=1:errors.append('multiple_continuation_commands');continue
            code,args=sent[0]['code'],sent[0]['args']
            end=next((x['args'] for x in reversed(previous) if x['code']==3),None)
            if code==4:
                if args!=['0']:errors.append('invalid_collect_command')
                if not end or len(end)<4 or not (int(end[2])>0 or end[0]=='1'):errors.append('collect_without_native_win_prompt')
            elif code==2:
                if args!=['6']:errors.append('unrecognized_feature_selection')
                if not any(x['code']==2 and x['args'][:2]==['5','1'] for x in previous):errors.append('feature_collect_without_native_prompt')
            elif code==7:
                if args!=[str(free_processed)]:errors.append('invalid_free_spin_counter')
                if not end or len(end)<4 or not (int(end[3])>0 or free_processed):errors.append('free_spin_without_native_prompt')
                free_processed+=1
            else:errors.append('unrecognized_or_additional_entry_command')
        previous=step.get('responses',[])
    return errors

def baseline_valid(proof):
    pinned=proof.get('sha256',{})
    required={'catalog-complete.json','coverage-audit.json','purchases-audit.json'}|{p+'/batches/1-100/audit.json' for p in ('endorphina','hacksaw','nolimit','elk')}
    return len(pinned)>=40 and required.issubset(pinned)

def verify_unavailable(doc):
    authority=doc.get('authority',{});summary=doc['summary'];trace=doc.get('trace',[])
    if summary.get('entry_sent') or any(x['code']==1 for step in trace for x in step.get('commands',[])):return ['unavailable_game_received_an_entry']
    if authority.get('practice')!=1 or authority.get('demo')!=2 or authority.get('game_id')!=doc['game']['id']:return ['unavailable_demo_identity_not_verified']
    reason=summary.get('unavailable_reason','')
    expected='Game not enabled. GameId:'+doc['game']['id']+' '
    if not reason.startswith(expected):return ['unavailable_reason_not_explicit']
    if not any(x['code']==101 and len(x['args'])>1 and x['args'][1]==reason for step in trace for x in step.get('responses',[])):return ['native_unavailability_proof_missing']
    if any(step.get('status')!='received' for step in trace):return ['uncertain_unavailable_session']
    return []

def verify(doc):
    errors=[];summary=doc['summary'];authority=doc.get('authority',{})
    if authority.get('practice')!=1 or authority.get('demo')!=2 or authority.get('currency')!='DEMO':errors.append('not_verified_public_demo')
    if summary.get('game_type') in ('craps','roulette','holdem','legacy_table','draw_game'):
        if summary['game_type']=='draw_game':
            from playngo_draw_games import verify_draw
            errors+=verify_draw(doc)
        elif summary['game_type']=='legacy_table':
            from playngo_legacy_tables import verify_legacy
            errors+=verify_legacy(doc)
        elif summary['game_type']=='holdem':
            from playngo_holdem import verify_holdem
            errors+=verify_holdem(doc)
        elif summary['game_type']=='roulette':
            from playngo_roulette import verify_roulette
            errors+=verify_roulette(doc)
        else:
            from playngo_craps import verify_table
            errors+=verify_table(doc)
        proof=doc.get('profile_proof',{});source=ROOT/proof.get('file','missing')
        if not source.is_file() or digest(source)!=proof.get('sha256'):errors.append('stale_table_source')
        for step in doc['trace']:
            for item in step.get('responses',[]):
                if item['code'] in (91,103) and any(v and v!='[REDACTED]' for v in item['args']):errors.append('sensitive_table_response_not_redacted')
        return errors
    profile=doc.get('profile',{});trace=doc.get('trace',[])
    errors+=continuation_errors(trace)
    outgoing=[x for s in trace for x in s.get('commands',[])]
    responses=[x for s in trace for x in s.get('responses',[])]
    entries=[x for x in outgoing if x['code']==1]
    if len(entries)!=1:errors.append('not_exactly_one_paid_entry')
    initial=[];native=[];started=False
    for step in trace:
        if any(x['code']==1 for x in step.get('commands',[])):started=True
        if started:native+=step.get('responses',[])
        else:initial+=step.get('responses',[])
        if step.get('status')!='received':errors.append('uncertain_request')
    before=next((x['args'] for x in reversed(initial) if x['code']==52),None)
    after=next((x['args'] for x in reversed(native) if x['code']==52),None)
    end=next((x['args'] for x in reversed(native) if x['code']==3),None)
    if not before or before[1]!='0' or not after or after[1]!='0' or not end or end[3]!='0':errors.append('native_round_not_closed')
    if any(x['code'] in (110,111) for x in responses):errors.append('native_error')
    if entries and before and after and end:
        args=entries[0]['args'];cost=int(args[0])*int(args[1])*int(args[2]);win=int(end[2])
        if int(before[0])-cost+win!=int(after[0]):errors.append('wallet_mismatch')
        for key,value in [('balance_before_native',int(before[0])),('balance_after_native',int(after[0])),('cost_native',cost),('win_native',win)]:
            if summary.get(key)!=value:errors.append('summary_mismatch:'+key)
        if profile.get('cost_native')!=cost:errors.append('profile_cost_mismatch')
    proof=doc.get('profile_proof',{})
    source=ROOT/proof.get('file','missing')
    if not source.is_file() or digest(source)!=proof.get('sha256'):errors.append('stale_profile_source')
    elif doc.get('settings_xml'):
        # Recompute the minimum profile from the saved public source, not summary fields.
        from playngo_rules import profile as native_profile
        from decimal import Decimal
        try:
            computed=native_profile(source.read_text(encoding='utf8'),[(x['code'],x['args']) for x in initial],doc['settings_xml'],doc.get('public_bet_configuration'))
            expected_lines=computed['lines']
            if summary['kind']=='go-ultra':
                from playngo_rules import modes
                mode=modes(source.read_text(encoding='utf8'),[(x['code'],x['args']) for x in initial])
                if not mode['go_ultra']:raise ValueError('unpublished_booster')
                expected_lines=int(Decimal(expected_lines)*Decimal(mode['factors'][0]))
            if entries and entries[0]['args'][:3]!=[str(computed['coins']),str(expected_lines),str(computed['denomination'])]:errors.append('entry_differs_from_public_profile')
        except Exception as exc:errors.append('public_profile_not_reproducible:'+str(exc))
    else:errors.append('public_denomination_settings_missing')
    for attempt in doc.get('previous_attempts',[]):
        archived=FOLDER/attempt['file']
        if not archived.is_file() or digest(archived)!=attempt['sha256']:errors.append('rejected_attempt_not_preserved')
    for x in responses:
        if x['code'] in (91,103) and any(v and v!='[REDACTED]' for v in x['args']):errors.append('sensitive_response_not_redacted')
    return errors

def audit():
    rows=read(FOLDER/'rounds.json',[]);issues=[];verified=[];hashes={};inventory=[];free_spin_requests=0;unavailable=[]
    for row in rows:
        path=FOLDER/'traces'/(row['case']+'.json');hashes[str(path.relative_to(ROOT)).replace('\\','/')]=digest(path)
        if row['status']=='unavailable':
            document=read(path);errors=verify_unavailable(document)
            if document['summary']!=row:errors.append('unavailable_index_mismatch')
            if errors:issues.append({'case':row['case'],'errors':errors})
            else:
                unavailable.append({'id':row['id'],'name':row['name'],'reason':row['unavailable_reason']})
                inventory.append({'id':row['id'],'name':row['name'],'slug':row['slug'],'normal_status':'unavailable','modes':[],'evidence':{'native_login_disabled':row['unavailable_reason']}})
            continue
        if row['status']!='completed':continue
        document=read(path);errors=verify(document)
        free_spin_requests+=sum(x['code']==7 for s in document['trace'] for x in s.get('commands',[]))
        if document['summary']!=row:errors.append('round_index_mismatch')
        game=document['game']
        if row['id']!=game['id'] or document.get('authority',{}).get('game_id')!=game['id']:errors.append('game_identity_mismatch')
        if errors:issues.append({'case':row['case'],'errors':errors})
        else:verified.append(row['case'])
        if row['kind']=='normal':
            from playngo_rules import modes
            proof=document.get('profile_proof',{});source=ROOT/proof.get('file','missing')
            initial=next(([(x['code'],x['args']) for x in s.get('responses',[])] for s in document['trace'] if any(x['code']==104 for x in s['commands'])),[])
            native_modes=modes(source.read_text(encoding='utf8'),initial) if source.is_file() else {'go_ultra':False,'error':'source_missing'}
            inventory.append({'id':row['id'],'name':row['name'],'slug':row['slug'],'normal_status':row['status'],'modes':['normal']+(['go-ultra'] if native_modes['go_ultra'] else []),'evidence':native_modes,'source_sha256':proof.get('sha256'),'game_type':row.get('game_type','slot')})
        proof=document.get('profile_proof',{})
        if proof.get('file'):hashes[proof['file']]=proof.get('sha256')
        for attempt in document.get('previous_attempts',[]):
            archived=FOLDER/attempt['file'];hashes[str(archived.relative_to(ROOT)).replace('\\','/')]=attempt['sha256']
    baseline=read(FOLDER/'previous-providers-proof.json',{})
    changed=[name for name,sha in baseline.get('sha256',{}).items() if not (ROOT/name).is_file() or digest(ROOT/name)!=sha]
    if not baseline_valid(baseline):issues.append({'case':'baseline','errors':['previous_provider_baseline_missing_or_incomplete']});changed.append('[baseline_missing_or_incomplete]')
    hashes.update(baseline.get('sha256',{}))
    normal=sum(row['kind']=='normal' and row['case'] in verified for row in rows)
    boosted=sum(row['kind']=='go-ultra' and row['case'] in verified for row in rows)
    expected_ids={g['id'] for g in read(FOLDER/'catalog.json',[])}
    normal_ids={r['id'] for r in rows if r['kind']=='normal' and r['case'] in verified}
    unavailable_ids={r['id'] for r in unavailable}
    expected_boosted={x['id'] for x in inventory if 'go-ultra' in x['modes']}
    verified_boosted={r['id'] for r in rows if r['kind']=='go-ultra' and r['case'] in verified}
    start,end=BATCHES[FOLDER.name];expected_normal=end-start
    passed=normal_ids|unavailable_ids==expected_ids and not normal_ids&unavailable_ids and len(expected_ids)==expected_normal and expected_boosted==verified_boosted and not issues and not changed
    write_json(FOLDER/'inventory.json',inventory)
    required_files=[ROOT/filename for filename in ('playngo_paths.py','playngo_client.py','playngo_protocol.py','playngo_rules.py','playngo_run.py','playngo_table_rules.py','playngo_craps.py','playngo_roulette.py','playngo_holdem.py','playngo_legacy_tables.py','playngo_draw_games.py','playngo_import.py','playngo_audit.py','playngo_reports.py','requirements.txt','playngo/catalog.json','playngo/sources.json')]
    required_files+=[FOLDER/filename for filename in ('catalog.json','rounds.json','inventory.json','previous-providers-proof.json')]
    for path in required_files:
        if path.is_file():hashes[str(path.relative_to(ROOT)).replace('\\','/')]=digest(path)
    result={'provider':'playngo','scope':'One normal entry for each first-100 game (Pass Line for GO CRAPS), plus every source-identified and natively enabled GoUltra control. Excludes exhaustive natural outcomes and other table bet selections.','normal_cases':normal,'go_ultra_cases':boosted,'verified_cases':len(verified),'verified_case_ids':sorted(verified),'expected_normal':100,'expected_go_ultra':len(expected_boosted),'scoped_coverage_passed':passed,'universal_mode_coverage_claimed':False,'passed':passed,'financial_cases_passed':not issues,'previous_providers_unchanged':not changed,'previous_provider_files':len(baseline.get('sha256',{})),'changed_previous_files':changed,'problems':issues,'pending_cases':[r['case'] for r in rows if r['status']!='completed'],'input_hashes':hashes}
    result['free_spin_requests_observed']=free_spin_requests
    result['table_samples']=[{'id':r['id'],'name':r['name'],'game_type':r['game_type'],'branch':r.get('variant',{'craps':'Pass Line','roulette':'Straight zero'}.get(r['game_type'],''))} for r in rows if r.get('game_type') in ('craps','roulette','holdem','legacy_table','draw_game') and r['status']=='completed']
    result['partial_deals_not_completed']=[{'case':r['case'],'file':a['file'],'status':a['status']} for r in rows for a in read(FOLDER/'traces'/(r['case']+'.json')).get('previous_attempts',[]) if a.get('status')=='accepted_partial_not_completed']
    result['batch']=FOLDER.name
    result['expected_normal']=expected_normal
    result['unavailable_games']=unavailable
    result['pending_cases']=[r['case'] for r in rows if r['status'] not in ('completed','unavailable')]
    result['scope']='One normal entry for each game in catalog batch '+FOLDER.name+', plus every source-identified and natively enabled GoUltra control. Excludes exhaustive natural outcomes and other table bet selections.'
    write_json(FOLDER/'audit.json',result);return result
if __name__=='__main__':
    result=audit();print(json.dumps({k:v for k,v in result.items() if k!='input_hashes'},ensure_ascii=True))
