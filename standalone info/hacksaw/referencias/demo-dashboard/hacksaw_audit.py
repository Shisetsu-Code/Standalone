"""Reconstruct coverage and wallet equations from saved native HTTP packets."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from hacksaw_protocol import check_round,choice_point,continuation,redact
from hacksaw_contracts import native_extra,mode_cases
from hacksaw_run import scope,read
from endorphina_run import write_json


def audit_inventory(meta,trace):
    steps=[s for s in trace if s.get('endpoint')=='/api/play/authenticate']
    if len(steps)!=1:raise ValueError('inventory_auth_evidence_missing')
    step=steps[0];auth=step['response'];request=step['request']
    if step.get('http_status')!=200 or auth.get('statusCode')!=0 or request.get('partner')!='demo' or request.get('mode')!=2 or auth.get('name')!='Demo' or str(auth.get('roundId'))!='0':raise ValueError('inventory_not_a_fresh_demo')
    if str(auth.get('gameId'))!=meta['id']:raise ValueError('inventory_game_differs')
    if meta.get('bonus_games')!=(auth.get('bonusGames') or []):raise ValueError('inventory_controls_differ')
    if Decimal(meta['minimum_bet'])!=min(Decimal(b) for b in auth['betLevels']):raise ValueError('inventory_minimum_differs')
    if meta.get('auth',auth)!=auth:raise ValueError('inventory_auth_differs')
    if redact(trace)!=trace:raise ValueError('unredacted_inventory_identifiers')


def audit_trace(packet):
    trace=packet['trace'];summary=packet['summary']
    if summary.get('status')!='completed' or summary.get('wallet_check')!='match':raise ValueError('summary_not_reconciled')
    if redact(trace)!=trace:raise ValueError('unredacted_identifiers')
    if any(s.get('http_status')!=200 or s.get('response',{}).get('statusCode')!=0 for s in trace):raise ValueError('unsuccessful_native_packet')
    auth_steps=[s for s in trace if s['endpoint']=='/api/play/authenticate']
    if len(auth_steps)!=1:raise ValueError('one_fresh_auth_required')
    auth=auth_steps[0]['response'];request=auth_steps[0]['request']
    if request.get('partner')!='demo' or request.get('mode')!=2 or auth.get('name')!='Demo' or str(auth.get('roundId'))!='0' or auth.get('roundStatus'):raise ValueError('not_a_fresh_demo')
    if str(auth['gameId'])!=summary['id'] or str(request['gameId'])!=summary['id']:raise ValueError('wrong_game')
    bets=[s for s in trace if s['endpoint']=='/api/play/bet']
    initial=[s for s in bets if s['request'].get('bets')]
    if len(initial)!=1 or bets[0] is not initial[0] or len(initial[0]['request']['bets'])!=1:raise ValueError('one_entry_per_trace_required')
    native_bet=initial[0]['request']['bets'][0]
    amount=str(native_bet['betAmount'])
    if Decimal(amount)!=min(Decimal(b) for b in auth['betLevels']):raise ValueError('not_the_published_minimum')
    bonus=native_bet.get('buyBonus');controls={b['bonusGameId']:b for b in auth.get('bonusGames') or []}
    if bonus and bonus not in controls:raise ValueError('unpublished_control')
    if bonus!=summary.get('bonus_id'):raise ValueError('wrong_purchase_id')
    expected_extra=native_extra(summary['id'],bonus,summary.get('base_mode'))
    if native_bet.get('customData')!=expected_extra.get('customData'):raise ValueError('native_custom_data_differs')
    multiplier=str(controls[bonus]['betCostMultiplier']) if bonus else '1'
    if bonus and summary.get('published_control')!=controls[bonus]:raise ValueError('control_contract_changed')
    before=auth['accountBalance']['balance'];responses=[s['response'] for s in bets]
    decisions=[]
    for previous,step in zip(bets,bets[1:]):
        current=previous['response']['round'];req=step['request']
        if req.get('bets') or req.get('roundId')!=current['roundId']:raise ValueError('continuation_round_mismatch')
        selected=req.get('continueInstructions',{}).get('action')
        if not selected or selected!=continuation(current,selected):raise ValueError('unoffered_continuation')
        point=choice_point(current)
        if point:decisions.append(dict(point,selected=selected))
    actual=check_round(before,amount,multiplier,responses)
    for field,value in dict(actual,balance_before=before,bet=amount,multiplier=multiplier).items():
        if field=='round_id' or field=='wallet_check':
            if summary.get(field)!=value:raise ValueError('summary_mismatch:'+field)
        elif Decimal(str(summary.get(field)))!=Decimal(value):raise ValueError('summary_mismatch:'+field)
    if summary.get('choices',[])!=decisions:raise ValueError('choice_metadata_not_native')
    return decisions


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',default='1-100');args=parser.parse_args()
    folder,games=scope(args.batch);issues=[]
    inventory=read(folder/'inventory.json',[])
    if len(inventory)!=len(games) or {r['id'] for r in inventory}!={g['id'] for g in games} or any(r['status']!='discovered' for r in inventory):issues.append({'error':'incomplete_inventory'})
    for meta in inventory:
        try:audit_inventory(meta,read(folder/'traces'/(meta['id']+'-initialization.json'),[]))
        except Exception as e:issues.append({'game':meta['id'],'error':str(e)})
    expected={g['id']+'--normal':None for g in games}
    modes={m['case']:m['base_mode'] for g in games for m in mode_cases(g)}
    expected.update({case:None for case in modes})
    for game in inventory:
        for i,control in enumerate(game.get('bonus_games') or []):expected[game['id']+'--buy-'+str(i)]=control['bonusGameId']
    rows=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])+read(folder/'choices.json',[])
    cases={r['case']:r for r in rows}
    if len(cases)!=len(rows):issues.append({'error':'duplicate_cases'})
    for case,bonus in expected.items():
        if case not in cases or cases[case].get('bonus_id')!=bonus or cases[case].get('base_mode')!=modes.get(case):issues.append({'case':case,'error':'required_case_missing_or_wrong_control'})
    goals={}
    for row in rows:
        try:
            root=row.get('root_case',row['case'])
            if root not in expected or row.get('bonus_id')!=expected[root]:raise ValueError('unexpected_root_or_control')
            if row.get('base_mode')!=modes.get(root):raise ValueError('unexpected_base_mode')
            packet=read(folder/'traces'/(row['case']+'.json'),{})
            if packet.get('summary')!=row:raise ValueError('trace_summary_index_mismatch')
            decisions=audit_trace(packet)
            for choice in decisions:
                for option in choice['options']:
                    key=root+':'+choice['node']+':'+option
                    goals[key]=goals.get(key,False) or choice['selected']==option
        except Exception as e:issues.append({'case':row['case'],'error':str(e)})
    missing=[key for key,verified in goals.items() if not verified]
    if missing:issues.append({'error':'unverified_native_choices','options':missing})
    matrix=read(folder/'choices-matrix.json',{}).get('summary',{})
    if matrix!={'options':len(goals),'verified':sum(goals.values())}:issues.append({'error':'choice_matrix_disagrees_with_packets'})
    prior=read(folder/'prior-providers-proof.json',{})
    for rel,digest in prior.items():
        if hashlib.sha256((folder.parents[2]/rel).read_bytes()).hexdigest()!=digest:issues.append({'error':'prior_provider_changed','file':rel})
    result={'provider':'hacksaw','games':len(games),'normal_cases':sum(r['kind']=='normal' and r['status']=='completed' for r in rows),
        'purchase_cases_required':sum(len(g.get('bonus_games') or []) for g in inventory)+len(modes),'purchase_cases_completed':sum(r['kind']=='purchase' and r['status']=='completed' for r in rows),
        'additional_base_modes':len(modes),
        'purchase_games':sum(bool(g.get('bonus_games')) for g in inventory),'activator_ids':sum(c['bonusGameId'].startswith('mod_') for g in inventory for c in g.get('bonus_games') or []),
        'internal_options_observed':len(goals),'internal_options_verified':sum(goals.values()),'additional_choice_rounds':sum(r['kind']=='choice' for r in rows),
        'recorded_rounds':len(rows),'states':dict(Counter(r['status'] for r in rows)),'passed':not issues,'issues':issues}
    write_json(folder/'audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='issues'}));print(json.dumps({'issue_count':len(issues),'first_issues':issues[:8]}))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
