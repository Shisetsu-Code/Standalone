"""Read-only replay audit: evidence is native replies, never runner status alone."""
import argparse
from collections import Counter
from decimal import Decimal,ROUND_HALF_UP,ROUND_DOWN
import hashlib
import json
import re
from pathlib import Path
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent
D=lambda value:Decimal(str(value))

def read(path,default=None):
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else default

def expected_controls(init):
    game=init['game'];result={};modes=init.get('allowedFeatureBets')
    if isinstance(modes,dict):
        for mode in init['allowedGameModes']:
            scoped=dict(init,allowedFeatureBets=modes[mode],game=dict(game,featureBuyTimesBetValue=game['featureBuyTimesBetValueAll'][mode]))
            if mode!=game['playedCapMode']:result[mode+'+NORMAL_PLAY']={'feature':None,'mode':mode,'base':D(1),'side':D(0),'type':'GAME_MODE'}
            for key,value in expected_controls(scoped).items():result[mode+'+'+key]=dict(value,mode=mode)
        return result
    allowed=set(modes if modes is not None else init.get('allowedGameFeatures',[]))
    for item in game.get('featureBuyTimesBetValue',[]):
        if item['name'] in allowed and item.get('type')!='SIDE_BET':
            result[item['name']]={'feature':item['name'],'base':D(item['price']),'side':D(0),'type':item['type']}
    contexts={'NORMAL_PLAY':{'feature':None,'base':D(1),'side':D(0)},**result}
    for context,base in contexts.items():
        for name,cost in game.get('sideBetCosts',{}).get(context,{}).items():
            if name in init.get('allowedGameFeatures',[]) and D(cost)>=0:
                result[context+'+'+name]=dict(base,side_name=name,side=D(cost),type='SIDE_BET')
    return result

def levels_for(init,control):
    mode=control.get('mode') or init['game'].get('playedCapMode')
    levels=init['betLevels'];levels=levels[mode] if mode in levels else levels
    values=levels.get('availableBetLevels',levels.get('betLevels',[]))
    features=init.get('featureBetLevels',{});features=features[mode] if mode in features else features
    return min(map(D,features.get(control.get('feature'),values)))

def audit_case(folder,row):
    checks=[]
    def require(condition,name):
        if not condition:raise ValueError(name)
        checks.append(name)
    if row['kind']=='normal':require(row['case']==row['code']+'--normal' and not row.get('control_id'),'normal_case_identity')
    if row['kind']=='purchase':require(row['case'].startswith(row['code']+'--buy-') and bool(row.get('control_id')),'purchase_case_identity')
    if row['kind']=='choice':require(re.fullmatch(re.escape(row['root_case'])+r'--choice-[1-9][0-9]*',row['case']) is not None,'choice_case_identity')
    document=read(folder/'traces'/(row['case']+'.json'),{})
    from nolimit_protocol import redact
    require(document==redact(document),'private_transport_identifiers_removed')
    require(document.get('summary')==row,'summary_matches_trace')
    steps=document.get('trace',[]);require(len(steps)>=3,'native_trace_present')
    replies=[]
    for step in steps:
        request=step['request'];matches=[r for r in step['responses'] if r.get('id')==request['id']]
        require(len(matches)==1,'one_matching_reply')
        require(not matches[0].get('error'),'provider_accepted')
        replies.append(matches[0])
    init=replies[0]
    require(steps[0]['request']['type']=='init' and init.get('init')=='ok' and init['game']['nextMode']=='NORMAL','fresh_native_init')
    require(init['currency']['code']=='EUR','demo_currency')
    controls=expected_controls(init)
    control=controls[row['control_id']] if row.get('control_id') else {'feature':None,'base':D(1),'side':D(0)}
    bet=levels_for(init,control);require(D(row['bet'])==bet,'published_minimum')
    money=lambda value:value.quantize(D('.01'),rounding=ROUND_HALF_UP)
    cost=money(bet*control['base'])+money(bet*control['side'])
    require(D(row['cost'])==cost,'published_entry_cost')
    entry=steps[1]['request']['content'];interaction=entry.get('playerInteraction',{})
    require(D(entry['bet'])==bet and entry['type']==('featureBet' if control['feature'] else 'normalBet'),'native_entry')
    require(entry.get('featureName')==control['feature'],'published_feature')
    require(interaction.get('sideBet')==control.get('side_name'),'published_side_context')
    if control.get('mode'):require(interaction.get('gameMode')==control['mode'],'published_game_mode')
    require(steps[-1]['request']['type']=='balance' and steps[-1]['request']['content']['type']=='balance','fresh_balance_read')
    games=[r['game'] for r in replies[1:-1]]
    require(games and games[-1]['nextMode']=='NORMAL','native_round_closed')
    before=D(init['balance']);after=D(replies[-1]['balance'])
    payout_field='totalRoundWin' if row['code']=='KitchenDramaSushiMania' and 'accumulatedRoundWin' not in games[-1] else 'accumulatedRoundWin'
    win=D(games[-1][payout_field])
    require(before==D(row['balance_before']) and after==D(row['balance_after']) and win==D(row['win']),'native_wallet_fields')
    require((before-cost+win).quantize(D('.01'),rounding=ROUND_DOWN)==after,'exact_wallet_equation_at_currency_precision')
    require(D(row['settled_win'])==after-before+cost,'settled_win_correct')
    require(D(row['rounding_adjustment'])==before-cost+win-after,'rounding_adjustment_correct')
    require(row['settlement_rule']=='truncate_final_balance_2dp','settlement_rule_correct')
    require(row.get('status')=='completed' and row.get('wallet_check')=='match','runner_status_supported')
    choices=iter(row.get('choices',[]));observations=[];choice_cost=D(0);target_used=False
    from nolimit_protocol import choice_point,continuation
    for index,game in enumerate(games[:-1],start=2):
        require(game['nextMode']!='NORMAL','no_second_paid_round')
        point=choice_point(game,row['code']);selected=None
        if point:
            choice=next(choices,None);require(choice is not None,'decision_recorded')
            selected=choice['selected'];require(selected in point['options'],'option_enabled')
            target=row.get('choice_target');expected=point.get('default','NO')
            if target and not target_used and target['node']==point['node'] and target['option'] in point['options']:
                expected=target['option'];target_used=True
            require(selected==expected,'bounded_choice_policy')
            require(all(choice.get(k)==v for k,v in point.items()),'native_menu_matches')
            require(D(choice['accumulated_before'])==D(game['accumulatedRoundWin']),'native_choice_balance')
            if selected!='NO':choice_cost+=D(point['published_costs'][selected])
            observations.append(choice)
        require(steps[index]['request']['content']==continuation(game,row['code'],selected),'native_continuation')
    require(next(choices,None) is None,'no_extra_choice_records')
    require(D(row.get('extra_spin_costs',0))==choice_cost,'internal_choice_costs')
    require(len(games)==row['native_game_responses'],'native_event_count')
    return {'case':row['case'],'passed':True,'game_responses':len(games),'decisions':len(observations),'cost':str(cost),'net_win':str(win),'balance_after':str(after)}

def audit(batch):
    folder=ROOT/'nolimit/batches'/batch;catalog=read(folder/'catalog.json',[]);inventory=read(folder/'inventory.json',[])
    rows=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])+read(folder/'choices.json',[])
    problems=[];cases=[];expected={}
    inv={r['code']:r for r in inventory}
    for game in catalog:
        code=game['code'];expected[code+'--normal']={'code':code,'kind':'normal','control_id':None};meta=inv.get(code,{})
        try:
            assert meta.get('status')=='discovered','initialization_missing'
            native=read(folder/'traces'/(code+'-initialization.json'))[0]['responses'][-1]
            assert native==meta['init'],'inventory_not_native'
            controls=expected_controls(native)
            assert set(controls)=={c['control_id'] for c in meta['controls']},'inventory_controls_incomplete'
            for control in meta['controls']:
                contract=controls[control['control_id']]
                assert D(control['multiplier'])==contract['base']+contract['side'],'inventory_price_not_native'
                assert control['type']==contract['type'] and control.get('feature_name')==contract['feature'] and control.get('side_name')==contract.get('side_name'),'inventory_control_not_native'
            expected.update({code+'--buy-'+str(i):{'code':code,'kind':'purchase','control_id':control['control_id']} for i,control in enumerate(meta['controls'])})
            mapped={r['case']:r.get('control_id') for r in rows if r['kind']=='purchase' and r['code']==code}
            for i,control in enumerate(meta['controls']):
                case=code+'--buy-'+str(i)
                if case in mapped:assert mapped[case]==control['control_id'],'case_control_identity_changed'
        except Exception as error:problems.append({'game':code,'error':str(error)})
    present={r['case'] for r in rows}
    if len(present)!=len(rows):problems.append({'error':'duplicate_case_ids'})
    for case in sorted(set(expected)-present):problems.append({'case':case,'error':'missing_expected_case'})
    for row in rows:
        try:
            identity=expected.get(row.get('root_case',row['case']))
            assert identity is not None,'unknown_base_identity'
            assert row['code']==identity['code'] and row.get('control_id')==identity['control_id'],'case_control_identity_mismatch'
            assert row['kind']==('choice' if row.get('root_case') else identity['kind']),'case_kind_identity_mismatch'
            cases.append(audit_case(folder,row))
        except Exception as error:problems.append({'case':row['case'],'error':str(error) or type(error).__name__})
    matrix=read(folder/'choices-matrix.json')
    from nolimit_history import history_points
    history=history_points(folder,[r for r in rows if r['kind']!='choice'])
    if matrix is None:problems.append({'error':'choice_matrix_missing'})
    else:
        verified={c['case'] for c in cases if c['passed']}
        observed={r['case']:{} for r in rows if r['kind']!='choice'}
        for row in rows:
            for choice in row.get('choices',[]):
                root=row.get('root_case',row['case'])
                for option in choice['options']:
                    key=choice['node']+':'+option
                    observed.setdefault(root,{}).setdefault(key,[])
                    if row['case'] in verified and choice['selected']==option:observed[root][key].append(row['case'])
        for item in history:
            for option in item['point']['options']:
                key=item['point']['node']+':'+option
                observed[item['root']].setdefault(key,[])
        if set(matrix.get('roots',{}))!=set(observed):problems.append({'error':'choice_root_set_mismatch'})
        for root,goals in matrix['roots'].items():
            if set(goals)!=set(observed.get(root,{})):problems.append({'root':root,'error':'observed_options_missing_from_matrix'})
            for key,goal in goals.items():
                evidence=set(observed.get(root,{}).get(key,[]))
                if not goal['verified'] or not set(goal['evidence'])&evidence:problems.append({'root':root,'error':'choice_not_verified','option':goal['option']})
    proof=read(folder/'prior-providers-proof.json',{})
    prior=[ROOT/'catalog-complete.json',*(ROOT/'endorphina/batches').glob('*/audit.json'),*(ROOT/'hacksaw/batches').glob('*/audit.json')]
    if set(proof)!={str(p.relative_to(ROOT)) for p in prior}:problems.append({'error':'previous_provider_proof_incomplete'})
    for name,digest in proof.items():
        if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:problems.append({'file':name,'error':'previous_provider_modified'})
    inputs=[folder/name for name in ('catalog.json','inventory.json','rounds.json','purchases.json','choices.json','choices-matrix.json','prior-providers-proof.json')]
    inputs+=[folder/'traces'/(r['case']+'.json') for r in rows]
    inputs+=[folder/'traces'/(g['code']+'-initialization.json') for g in catalog]
    inputs+=[folder/source for source in sorted({h['source'] for h in history})]
    hashes={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs if p.exists()}
    for name in ('nolimit_audit.py','nolimit_client.py','nolimit_protocol.py','nolimit_run.py','nolimit_reconcile.py','nolimit_sanitize.py','nolimit_history.py'):
        hashes['../../../'+name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    result={'passed':not problems,'batch':batch,'games':len(catalog),'expected_base_cases':len(expected),'cases':len(rows),'verified_cases':len(cases),'native_game_responses':sum(c['game_responses'] for c in cases),'problems':problems,'case_results':cases,'input_hashes':hashes}
    write_json(folder/'audit.json',result)
    from nolimit_reports import render
    render(batch)
    print(json.dumps({k:v for k,v in result.items() if k not in ('problems','case_results','input_hashes')}));print(json.dumps(problems[:15]))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',default='1-100');args=parser.parse_args();audit(args.batch)
