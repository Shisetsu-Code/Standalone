"""Reproduce local native-journal audit and assemble a secret-free evidence bundle.

No network calls or gameplay. Credentials and captured HAR bodies are excluded.
"""
import hashlib
import json
from pathlib import Path
import shutil
from collections import Counter
from protocol import audit_round, minimum_modes, settlement_rejected

ROOT = Path(__file__).resolve().parent.parent

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')

def reference(path):
    return {'path':path.relative_to(ROOT).as_posix(), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    assert not (ROOT/'private/campaign.lock').exists(), 'executor_lock_present'
    catalogue = read(ROOT/'results/catalogue.json')
    report = read(ROOT/'results/provider-report.json')
    assert len(catalogue)==75 and len({x['game_id'] for x in catalogue})==75
    games = {g['id']:g for g in report['games']}
    audited=[]; holds=[]; evidence=set(); steps=0
    for game in catalogue:
        gid=game['game_id']; planpath=ROOT/'private/plans'/f'{gid}.json'
        plan=read(planpath)
        assert plan['modes']==minimum_modes(plan['info']), gid
        evidence.add(planpath)
        for profile in plan['modes']:
            path=ROOT/'private/rounds'/f"{gid}--{profile['id']}.json"
            if not path.exists():
                assert (ROOT/'private/holds'/f'{gid}.json').exists(), 'unexplained_missing_mode'
                continue
            row=read(path); folder=ROOT/'private/sessions'/row['session']
            journals={p:read(p) for p in folder.glob('*.json') if p.name!='credentials.json'}
            info=read(folder/'information.json')['response']
            assert profile in minimum_modes(info), 'mode_not_native_minimum'
            for name in ['configuration.json','authentication.json','information.json','recovery.json']:
                evidence.add(folder/name)
            evidence.add(path)
            play=read(folder/(profile['id']+'-play.json'))
            assert play['http_status']==200 and play['request']==row['play_request'] and play['response']==row['play_response']
            evidence.add(folder/(profile['id']+'-play.json'))
            last=row['play_response']
            for item in row.get('continuations',[]):
                matching=[p for p,j in journals.items() if j.get('path')=='/game/play' and j.get('request')==item['request'] and j.get('response')==item['response'] and j.get('http_status')==200]
                assert len(matching)==1, 'continuation_journal_binding'
                evidence.add(matching[0]);last=item['response']
            completes=[(p,j) for p,j in journals.items() if j.get('path')=='/game/complete' and j.get('request',{}).get('roundId')==last['roundId']]
            assert len(completes)==1, 'settlement_attempt_count'
            completepath,complete=completes[0]; evidence.add(completepath)
            mode=next(m for m in games[gid]['modes'] if m['id']==profile['id'])
            if row['status']=='verified':
                assert complete['http_status']==200
                assert complete['request']==row['complete_request'] and complete['response']==row['complete_response']
                audit=audit_round(row['balance_before'],info,play['request'],play['response'],complete['request'],complete['response'],row.get('continuations'))
                assert audit==row['audit'], 'saved_audit_mismatch'
                # Establish the before balance independently from the session ledger.
                previous=[j for j in journals.values() if j.get('path')=='/game/complete' and j.get('http_status')==200 and j['started_at']<play['started_at']]
                expected=max(previous,key=lambda j:j['started_at'])['response']['balance'] if previous else read(folder/'authentication.json')['response']['balance']
                assert expected==row['balance_before'], 'session_balance_chain'
                steps+=audit['internal_steps']; audited.append({'game':gid,'mode':profile['id'],'round_id':last['roundId'],'audit':audit})
                mode['evidence']=[reference(p) for p in sorted(evidence & ({path,planpath,folder/'configuration.json',folder/'authentication.json',folder/'information.json',folder/'recovery.json',folder/(profile['id']+'-play.json'),completepath} | {p for p,j in journals.items() if j.get('path')=='/game/play' and j.get('request',{}).get('roundId')==last['roundId']}))]
            else:
                holdpath=ROOT/'private/holds'/f'{gid}.json'
                assert holdpath.exists() and settlement_rejected(last,complete), 'unexplained_unverified_round'
                evidence.add(holdpath);holds.append({'game':gid,'mode':profile['id'],'round_id':last['roundId'],'status':'settlement_rejected_not_replayed','wallet_reconciled':False,'evidence':reference(completepath)})
    conditional=[];conditional_verified=0;preparations=0
    for path in (ROOT/'private/conditional-offers').glob('*.json'):
        offer=read(path);evidence.add(path)
        for action in offer['actions']:
            casepath=ROOT/'private/conditional-cases'/(action+'.json')
            if not casepath.exists() or read(casepath).get('status')!='verified':
                conditional.append({'game':offer['game'],'parent_mode':offer['parent_mode'],'actions':[action],'status':'pending_contract_and_state_bound_price','evidence':reference(path)})
                continue
            row=read(casepath);folder=ROOT/'private/sessions'/row['session']
            journals={p:read(p) for p in folder.glob('*.json') if p.name!='credentials.json'}
            play=read(folder/'preparation-play.json');complete=read(folder/'complete.json');info=read(folder/'information.json')['response'];auth=read(folder/'authentication.json')['response']
            assert row['play_request']==play['request'] and row['play_response']==play['response'] and play['http_status']==200
            assert row['balance_before']==auth['balance'] and row['preparation_mode'] in minimum_modes(info)
            assert row['complete_request']==complete['request'] and row['complete_response']==complete['response'] and complete['http_status']==200
            assert len([j for j in journals.values() if j.get('path')=='/game/complete'])==1
            assert sum(c['request'].get('action')==action for c in row['continuations'])==1
            for c in row['continuations']:
                assert len([j for j in journals.values() if j.get('path')=='/game/play' and j.get('request')==c['request'] and j.get('response')==c['response'] and j.get('http_status')==200])==1
            audit=audit_round(auth['balance'],info,play['request'],play['response'],complete['request'],complete['response'],row['continuations'])
            assert audit==row['audit']
            selected={casepath,path}|set(journals)
            evidence.update(selected)
            mode=next(m for m in games[offer['game']]['modes'] if m['id']==offer['parent_mode']+'::offer::'+action)
            extra=next(c for c in row['continuations'] if c['request']['action']==action)
            mode.update(status='verified_remote',cost=extra['request']['bet'],payout=extra['response']['wager']['win'],
                        checks={k:True for k in ['demo','action_binding','cost','result','round_closed','balance']},
                        evidence=[reference(p) for p in sorted(selected)],preparation={'mode':offer['parent_mode'],'cost':row['preparation_cost'],'counted_as_new_parent_mode_coverage':False},compound_round_audit=audit)
            audited.append({'game':offer['game'],'mode':mode['id'],'round_id':play['response']['roundId'],'audit':audit,'parent_is_preparation_only':True})
            steps+=audit['internal_steps'];conditional_verified+=1;preparations+=1
    # Check all configured conditional purchase types, including unobserved offers.
    configured=set()
    for path in (ROOT/'private/plans').glob('*.json'):
        plan=read(path)
        for state in plan['info'].get('config',{}).get('per_state',{}).values():
            for offer in state.get('continuation_offers',[]):
                for action in offer.get('actions',[]):
                    if action.get('kind')!='Take':configured.add((plan['game'],action['name']))
    assert configured=={(read(p)['game'],a) for p in (ROOT/'private/conditional-offers').glob('*.json') for a in read(p)['actions']}, 'conditional_inventory_gap'
    for game in report['games']:
        if all(m['status']=='verified_remote' for m in game['modes']):game['status']='complete'
    statuses=Counter(m['status'] for g in report['games'] for m in g['modes'])
    summary={'catalogue_games':75,'verified_modes':len(audited),'internal_steps':steps,'mode_statuses':dict(statuses),'game_statuses':dict(Counter(g['status'] for g in report['games'])),'held_games':len(holds),'conditional_types_verified':conditional_verified,'conditional_types_pending':len(conditional),'additional_parent_preparations_not_mode_coverage':preparations,'overall_status':'partial_with_explicit_pending_cases','all_modes_complete':False,'fresh_demo_only':True,'captured_har_cycles_separate':16,'additional_har_extra_purchases_separate':56,'scope':'One native-minimum normal round and each identified nonnormal mode; no exhaustive stake or line permutations.'}
    report.update(summary=summary,settlement_holds=holds,conditional_pending=conditional)
    write(ROOT/'results/provider-report.json',report)
    write(ROOT/'results/final-audit.json',{'summary':summary,'reproduction':'python -B -X utf8 code/final_audit.py','verified_rounds':audited,'holds':holds,'conditional_pending':conditional})
    for p in (ROOT/'private/references').glob('*'):
        if p.is_file():evidence.add(p)
    for p in (ROOT/'private/client-sources').rglob('*.journal.json'):evidence.add(p)
    for p in (ROOT/'private/bloody-har').glob('*'):
        if p.is_file():evidence.add(p)
    evidence.update((ROOT/'results').glob('*.json'))
    evidence.update((ROOT/'code').glob('*.py'))
    bundle=ROOT/'export/peterandsons-evidence-bloody-update'
    bundle.mkdir(parents=True,exist_ok=True)
    entries=[]
    secrets=[str(value).encode() for credential in (ROOT/'private/sessions').glob('*/credentials.json') for key,value in read(credential).items() if key in ('key','token') and value]
    for path in sorted(evidence):
        assert path.is_relative_to(ROOT) and path.name!='credentials.json' and path.suffix.lower()!='.har'
        # Reject leaked own credential values in all exported bytes.
        data=path.read_bytes()
        if any(value in data for value in secrets):raise ValueError('secret_in_export:'+str(path))
        dest=bundle/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
        entries.append(reference(path))
    write(bundle/'manifest.json',{'provider':'peterandsons','summary':summary,'files':entries,'credentials_included':False,'raw_har_included':False})
    print(json.dumps({'summary':summary,'bundle':str(bundle),'files':len(entries)},ensure_ascii=False))

if __name__=='__main__':main()
