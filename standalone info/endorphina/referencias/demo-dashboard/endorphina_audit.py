"""Recompute demo coverage and wallets from native messages, without network."""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
from endorphina_paths import batch_path,catalog_slice,private_path,unavailable_slugs
from endorphina_client import matches_reply
from endorphina_choices import point,CONFIG
from endorphina_risk_contract import options as risk_options
from endorphina_run import write_json

ROOT=batch_path()


def native_choices(trace,slug):
    history=None
    found=[]
    for step in trace:
        req=step['request']
        if req['method']=='STEP_FEATURE' and history:
            active=[f for f in history['features'] if f['status']=='IN_PROGRESS']
            choice=point(active[-1],slug) if active else None
            if choice:
                value=req['payload'].get(choice['field'])
                if req['payload'].get('@type')!=choice['action_type'] or value not in choice['options']:
                    raise ValueError('unpublished_internal_choice')
                found.append(dict(choice,selected=value))
        messages=[m for m in step['responses'] if matches_reply(m,req['requestId'])]
        payload=messages[-1].get('payload') if messages else None
        if not isinstance(payload,dict):continue
        if req['method'] in ('GET_LAST_GAME','END_FEATURE') and 'features' in payload:history=payload
        elif req['method'] in ('START_GAME','END_GAME'):history=payload.get('data',history)
        elif req['method']=='STEP_FEATURE':history=payload.get('historyItem',history)
    return found


def verify(row, trace, inventory, require_status=True):
    errors=[]
    if require_status and row.get('status')!='completed':errors.append('not_completed')
    if require_status and row.get('wallet_check')!='match':errors.append('wallet_not_marked_reconciled')
    history=None
    balance=None
    before=None
    paid=[]
    risk=[]
    for step in trace:
        request=step['request']
        method=request['method']
        if method=='START_GAME':
            paid.append(request['payload'])
            before=balance
        if method=='STEP_FEATURE' and '.gamble.' in request.get('payload',{}).get('@type',''):
            risk.append(request['payload'])
        matched=[r for r in step['responses'] if matches_reply(r,request['requestId'])]
        if not matched:errors.append('request_without_response');continue
        payload=matched[-1].get('payload')
        if not isinstance(payload,dict):continue
        if method=='GET_BALANCE':balance=payload.get('balance')
        if method in ('START_GAME','END_GAME'):
            history=payload.get('data',history)
            balance=payload.get('balance',{}).get('balance',balance)
        elif method=='STEP_FEATURE':history=payload.get('historyItem',history)
        elif method in ('GET_LAST_GAME','END_FEATURE') and 'features' in payload:history=payload
    if len(paid)!=1:errors.append('paid_request_count')
    if not history or history.get('status')!='FINISHED':errors.append('provider_round_not_finished')
    if before is None or balance is None:errors.append('missing_native_balance')
    if errors:return errors
    params=paid[0]
    table=inventory['paytable']
    if params['bet_per_line'] not in table['bets_set'] or params['num_of_lines'] not in table['lines_set'] or Decimal(params['denom']) not in [Decimal(x) for x in table['denoms_set']]:errors.append('unpublished_bet')
    buy=params.get('buyInId')
    price=Decimal(1)
    if buy:
        option=next((b for b in inventory.get('buy_ins') or [] if b['id']==buy),None)
        if not option:errors.append('unpublished_purchase')
        else:price=Decimal(str(option['price']))
        if row.get('buy_id')!=buy:errors.append('purchase_id_mismatch')
    elif row.get('kind') in ('purchase','purchase_choice'):errors.append('missing_purchase_id')
    cost=(Decimal(str(params['bet_per_line']))*params['num_of_lines']+Decimal(str(params.get('extra_bet') or 0)))*Decimal(params['denom'])*price
    win=sum(Decimal(str(f['current_win'])) for f in history['features'])*Decimal(history['betting_param']['denom'])
    if Decimal(before)-cost+win!=Decimal(balance):errors.append('native_wallet_mismatch')
    if Decimal(str(row['cost']))!=cost or Decimal(str(row['final_win']))!=win or Decimal(str(row['balance_before']))!=Decimal(before) or Decimal(str(row['balance_after']))!=Decimal(balance):errors.append('summary_does_not_match_native_messages')
    if row.get('kind')=='risk':
        published=risk_options(CONFIG.get(row['slug'],[]))
        if not 0<=row['option']<len(published):return errors+['unpublished_risk_option']
        control=published[row['option']]
        if row.get('risk_control',control)!=control:errors.append('risk_contract_mismatch')
        if not any(a.get('@type')=='logic.api.gamelogic.gamble.'+control['type'] and a.get(control['field'])==control['value'] for a in risk):errors.append('risk_option_not_sent')
    if row.get('kind') not in ('risk',) and risk:errors.append('unexpected_risk_request')
    return errors


def main():
    inv=json.loads((ROOT/'inventory.json').read_text(encoding='utf8'))
    catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf8'))
    metadata={r['slug']:r for r in inv}
    files=['rounds.json','purchases.json','risk.json','choices.json']
    rows=[r for name in files if (ROOT/name).exists() for r in json.loads((ROOT/name).read_text(encoding='utf8'))]
    expected={g['slug']+'--normal' for g in catalog}
    expected.update(r['slug']+'--buy-'+str(i) for r in inv for i,_ in enumerate(r.get('buy_ins') or []))
    configs=json.loads((ROOT/'features.json').read_text(encoding='utf8'))
    controls={r['slug']:risk_options(r['features']) for r in configs}
    expected.update(g['slug']+'--risk-'+str(i) for g in catalog for i in range(len(controls[g['slug']])))
    issues=[]
    unavailable=unavailable_slugs()
    menu_goals={}
    if not catalog or len({g['id'] for g in catalog})!=len(catalog) or len(inv)!=len(catalog) or any(r['status']!='discovered' and not (r['status']=='unavailable' and r['slug'] in unavailable) for r in inv):issues.append({'error':'catalog_inventory_incomplete'})
    actual={r['case'] for r in rows}
    if expected-actual:issues.append({'error':'missing_required_cases','cases':sorted(expected-actual)})
    for row in rows:
        if row.get('status')=='unavailable' and row['slug'] in unavailable and row.get('kind')=='normal':continue
        try:
            trace=json.loads((ROOT/'traces'/(row['case']+'.json')).read_text(encoding='utf8'))['trace']
            errors=verify(row,trace,metadata[row['slug']])
            observed=native_choices(trace,row['slug'])
            if row.get('kind') in ('purchase','purchase_choice'):
                root=row.get('root_case',row['case'])
                for choice in observed:
                    for option in choice['options']:
                        key=(root,choice['node'],option)
                        menu_goals.setdefault(key,False)
                        if not errors and choice['selected']==option:menu_goals[key]=True
        except Exception as e:errors=['audit_exception:'+type(e).__name__]
        if errors:issues.append({'case':row['case'],'errors':errors})
    missing_menus=[{'case':k[0],'node':k[1],'option':k[2]} for k,v in menu_goals.items() if not v]
    if missing_menus:issues.append({'error':'internal_choices_incomplete','choices':missing_menus})
    result={'provider':'endorphina','games':len(catalog),'required_entry_cases':len(expected),
        'normal_cases':sum(r.get('kind')=='normal' and r['status']=='completed' for r in rows),'unavailable_games':len(unavailable),'advertised_purchase_cases':sum(len(r.get('buy_ins') or []) for r in inv),
        'purchase_games':sum(bool(r.get('buy_ins')) for r in inv),'risk_options_required':sum(len(v) for v in controls.values()),
        'risk_options_completed':sum(r.get('kind')=='risk' and r.get('status')=='completed' and r.get('wallet_check')=='match' for r in rows),
        'additional_choice_trials':sum(r.get('kind')=='purchase_choice' for r in rows),
        'internal_options_observed':len(menu_goals),'internal_options_verified':sum(menu_goals.values()),
        'warmup_rounds':sum(r.get('kind')=='risk_warmup' for r in rows),'recorded_rounds':sum(r['status']!='unavailable' for r in rows),
        'states':dict(Counter(r['status'] for r in rows)),'passed':not issues,'issues':issues,
        'scope':'Native protocol and fictional demo balances; not visual certification of all animations or every random outcome. Diagnostic failed attempts are preserved separately.'}
    write_json(ROOT/'audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('issues','scope')},ensure_ascii=False))
    print(json.dumps({'issue_count':len(issues),'first_issues':[dict(i,cases=i['cases'][:3]) if 'cases' in i else i for i in issues[:8]]}))
    if issues:raise SystemExit(1)


if __name__=='__main__':main()
