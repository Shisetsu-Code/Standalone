"""Independent read-only evidence checks for the ELK first-100 demo batch."""
import argparse,hashlib,json
from decimal import Decimal
from pathlib import Path
from elk_protocol import parse_xml,redact_xml
from endorphina_run import write_json
from elk_paths import batch_path,catalog_slice,BATCHES

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'elk/batches/1-100'
D=Decimal

def read(path,default=None):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prior_paths(batch='1-100'):
    paths=[ROOT/'catalog-complete.json',*[p for provider in ('endorphina','hacksaw','nolimit') for p in (ROOT/provider/'batches').glob('*/audit.json')]]
    if batch=='101-159':
        first=batch_path('1-100');paths+=[first/name for name in ('catalog.json','inventory.json','rounds.json')]+sorted((first/'traces').glob('*.json'))
    return paths
def snapshot(batch='1-100'):
    folder=batch_path(batch);folder.mkdir(parents=True,exist_ok=True)
    target=folder/'prior-providers-proof.json'
    if target.exists():raise ValueError('proof_already_exists')
    write_json(target,{str(p.relative_to(ROOT)):digest(p) for p in prior_paths(batch)})

def controls_from_native(root):
    levels=root.find('betlevels');flag=root.find('gameprops/bmode');found={}
    if levels is None:raise ValueError('no_betlevels')
    enabled=levels.get('bmode')=='true' and (flag is None or flag.get('enabled')=='true')
    for level in levels.findall('betlevel'):
        modes=[(m.get('id'),m.get('amount')) for m in level.findall('bmodes/bmode')]
        if not modes and level.get('amount'):modes=[('DEF',level.get('amount'))]
        for name,amount in modes:
            if (name=='DEF' or enabled) and D(amount)>0:
                candidate=(D(amount),int(level.get('id')),amount)
                if name not in found or candidate[:2]<found[name][:2]:found[name]=candidate
    if 'DEF' not in found:raise ValueError('no_normal_control')
    base={k:{'mode':k,'betlevel':str(v[1]),'amount':v[2]} for k,v in found.items()}
    variants=root.findall('variants/variant')
    if not variants:return base
    result={}
    for variant in variants:
        table=parse_xml(variant.findtext('game/paytable'));prices={m.get('name'):D(m.get('price')) for m in table.findall('BMODES/BMODE')}
        for name,control in base.items():
            if prices and name not in prices:continue
            if prices and D(control['amount'])/D(base['DEF']['amount'])!=prices[name]/prices['DEF']:raise ValueError('native_variant_price_mismatch')
            result[name+'@'+variant.get('id')]=dict(control,variant=variant.get('id'))
    return result

def audit_case(document):
    if document.get('campaign'):
        from elk_boss_audit import verify_target
        return verify_target(document)
    row=document['summary'];trace=document['trace']
    def require(ok,message):
        if not ok:raise ValueError(message)
    game=document['game'];launch=document['launch']
    require(launch.get('mode')=='demo' and launch.get('operatorid')=='44' and launch.get('currency')=='EUR' and launch.get('capi')=='https://gc5-stage.contentmedia.eu/capi','public_demo_authority')
    require(launch.get('gameid')==game['id']==row['id'] and row['slug']==game['slug'],'game_identity')
    variant=row.get('control',{}).get('variant');suffix='--variant-'+variant if variant else ''
    require(row['case']==game['slug']+'--'+row['mode']+suffix,'case_identity')
    require(len(trace)==3 and [t['method'] for t in trace]==['init','purchase','checkwin'],'one_paid_entry_then_check')
    for t in trace:
        require(t.get('status')=='received' and t.get('http_status')==200,'successful_native_transport')
        require(redact_xml(t['request'])==t['request'] and redact_xml(t['response'])==t['response'],'private_identifiers_removed')
    requests=[parse_xml(t['request']) for t in trace];init,buy,check=[parse_xml(t['response']) for t in trace]
    require([x.findtext('method') for x in (init,buy,check)]==['init','purchase','checkwin'],'native_methods')
    require(all(x.findtext('errorcode')=='0' for x in (init,buy,check)),'native_acceptance')
    require(init.findtext('roundid')=='0' and D(init.findtext('gamesession/totbet'))==0 and D(init.findtext('gamesession/totwon'))==0,'fresh_session')
    controls=controls_from_native(init);control=controls[row['mode']+('@'+variant if variant else '')];require(row['control']==control,'published_minimum')
    primary=next(c for c in controls.values() if c['mode']=='DEF')
    require(row['kind']==('normal' if control==primary else 'variant' if row['mode']=='DEF' else 'purchase'),'case_kind')
    entry=requests[1];expected_mode=control['mode'] if init.find('betlevels').get('bmode')=='true' else None
    require(entry.get('bmode')==expected_mode and entry.get('betlevel')==control['betlevel'] and D(entry.get('amount'))==D(control['amount']),'native_purchase_request')
    require(entry.get('variant')==variant,'published_variant_request')
    require(entry.get('cur')=='EUR' and requests[0].get('cur')=='EUR' and requests[0].get('opid')=='44','demo_request_currency')
    rid=buy.findtext('roundid');info=buy.find('roundinfo')
    require(bool(rid) and rid.startswith('round-') and rid==info.findtext('roundid')==check.findtext('roundid')==requests[2].get('roundid')==row['round_id'],'round_correlation')
    require(info.findtext('bmode')==row['mode'] and info.findtext('betlevel')==control['betlevel'],'native_mode_level')
    cost=D(info.findtext('betamount'));win=D(info.findtext('winamount'));before=D(init.findtext('player/balance'));after=D(check.findtext('player/balance'))
    require(all(x.findtext('player/currency')=='EUR' for x in (init,buy,check)) and info.findtext('currency')=='EUR','native_currency')
    require(cost==D(control['amount'])==D(row['cost']) and win==D(row['win']) and win>=0,'native_money')
    require(before==D(row['balance_before']) and after==D(row['balance_after'])==D(info.findtext('balanceafterwin')) and before-cost+win==after,'exact_wallet_equation')
    require(D(check.findtext('gamesession/totbet'))==cost and D(check.findtext('gamesession/totwon'))==win,'native_session_totals')
    if check.find('gamesession/netposition') is not None:require(D(check.findtext('gamesession/netposition'))==win-cost,'native_net_position')
    pub=parse_xml(buy.findtext('game/pubdata'));purchases=pub.findall('PURCHASE');require(pub.tag=='PURCHASES' and len(purchases)==1,'one_native_purchase')
    purchase=purchases[0];require(purchase.get('bmode')==expected_mode and D(purchase.get('winamount'))==win and purchase.get('currency','EUR')=='EUR','pubdata_native_total')
    if purchase.get('betamount') is not None:require(D(purchase.get('betamount'))==cost,'pubdata_native_cost')
    else:require(expected_mode is None and purchase.get('betcoins') is not None,'classic_native_cost_missing')
    if purchase.get('betlevel') is not None:require(purchase.get('betlevel')==control['betlevel'],'pubdata_level')
    else:
        table=parse_xml(init.findtext('game/paytable'))
        if purchase.get('revision') or table.get('revision'):require(bool(purchase.get('revision')) and purchase.get('revision')==table.get('revision'),'legacy_math_revision')
        else:require(init.find('betlevels').get('bmode')=='false' and (table.get('protocol-version')=='2' or table.tag in ('SETUP','MODES') and bool(table.findall('CONFIG'))),'classic_native_contract')
        native_mode=next(m for level in init.findall('betlevels/betlevel') if level.get('id')==control['betlevel'] for m in level.findall('bmodes/bmode') if m.get('id')==control['mode'])
        coin=D(native_mode.get('coinvalue'))
        if purchase.get('coinvalue') is not None:require(D(purchase.get('coinvalue'))==coin,'legacy_native_coin_value')
        bet_coins=purchase.get('betcoins',purchase.get('bet'))
        if bet_coins is not None:require(D(bet_coins)*coin==cost,'legacy_native_bet_coins')
        else:require(purchase.get('betamount') is not None and D(purchase.get('betamount'))==cost,'classic_native_entry_money')
        win_coins=purchase.get('win',purchase.get('wintot'))
        if win_coins is None:win_coins=purchase.findall('RESULT')[-1].get('wintotal')
        require(win_coins is not None and D(win_coins)*coin==win,'legacy_native_win_coins')
    if variant:require(purchase.get('variant')==variant,'native_variant_reply')
    native=purchase.findall('RESULT');recorded=document.get('results',[])
    require(len(native)>0 and len(native)==len(recorded)==row['native_results'],'all_result_steps_preserved')
    table=init.findtext('game/paytable')
    if variant:table=next(v for v in init.findall('variants/variant') if v.get('id')==variant).findtext('game/paytable')
    # These two public demos reuse the provider's underlying math/paytable IDs.
    math_aliases={'10263':'10206','10262':'10216'}
    if table:require(parse_xml(table).get('gameid') in (None,row['id'],math_aliases.get(row['id'])),'native_paytable_identity')
    allowed={m.get('name') for m in parse_xml(table).findall('MODE')} if table else {'BASE','BONUS'}
    if table and not parse_xml(table).findall('MODE') and expected_mode is None:
        configs=parse_xml(table).findall('CONFIG');require(bool(configs),'classic_native_configs')
        ids=[c.get('id') for c in configs]
        require(all(x is None for x in ids) or all(x is not None for x in ids),'classic_identifier_scheme')
        allowed=set(ids) if all(x is not None for x in ids) else {str(index) for index in range(len(configs))}
        if parse_xml(table).tag=='MODES':
            require(all(n.get('mode') is not None or n.get('freespin',n.get('freespins')) in ('0','1') for n in native),'classic_spin_flags')
            allowed.add(None)
    if table and parse_xml(table).get('gameid')=='10053' and 'FREESPINS-AVALANCHE' in allowed:
        allowed.update('FREESPINS-'+name for name in list(allowed) if name in {'AVALANCHE-4','AVALANCHE-5','AVALANCHE-6','AVALANCHE-7','AVALANCHE-8'})
    require(all(n.tag=='RESULT' for n in purchase) and all(n.get('mode') in allowed for n in native),'published_result_sequence')
    last=native[-1]
    for field in ('freespin','freespins','fsleft'):
        if last.get(field) is not None:require(D(last.get(field))==0,'classic_bonus_exhausted')
    for action in last.findall('ACTIONS'):
        if action.get('fscount') is not None:require(D(action.get('fscount'))==0,'classic_bonus_actions_exhausted')
    indices=[node.get('resultIndex') for node in native]
    if any(index is not None for index in indices):require(all(index is not None for index in indices) and [int(index) for index in indices]==list(range(len(native))),'native_result_order')
    if last.get('amounttotal') is not None:require(D(last.get('amounttotal'))==win,'last_result_native_total')
    continuation_names={'bonus-counter','freedrops','redrops','free-drops','free-spins','respins','freespins','subrounds','dropz','respins-base','respins-bonus','extra-drops','kitty-free-drops','drops','coin-game-counter','lives','sub-rounds','coin-chase-counter','','bonus-symbols','super-bonus-symbols','both-ways','life-lines','bonus spins','casino spins','spins','extras','bonus-spins','progress','base-multiplier','levels','features-collected','bonus-respins'}
    meter_names={'win-multiplier','multiplier','collect-bonuses','body-counter','win multiplier','remembered-multiplier'}
    for counter in last.findall('COUNTERS/COUNTER'):
        name=counter.get('name');require(name in continuation_names|meter_names,'recognized_native_counter')
        if name not in meter_names and D(counter.get('left','0'))>0:
            terminal=any(a.get('name')=='bonus-summary' and a.get('bonus-counter-left')=='0' for a in last.iter('ACTION'))
            require(row['id']=='10246' and name=='bonus-counter' and terminal and counter.get('current') is None and counter.get('decrease') is None,'native_bonus_exhausted')
    import xml.etree.ElementTree as ET
    for index,(node,saved) in enumerate(zip(native,recorded)):
        require(saved=={'step':index,'mode':node.get('mode'),'attributes':dict(node.attrib),'xml':ET.tostring(node,encoding='unicode')},'native_step_unchanged')
    require(row['status']=='completed' and row['closed'] is True and row['wallet_check']=='match','status_supported')
    return {'case':row['case'],'native_results':len(native),'passed':True}

def audit(batch='1-100'):
    FOLDER=batch_path(batch)
    from elk_boss_audit import CACHE
    CACHE.clear()
    catalog=read(FOLDER/'catalog.json',[]);inventory=read(FOLDER/'inventory.json',[]);rows=read(FOLDER/'rounds.json',[]);problems=[];passed=[]
    if catalog!=catalog_slice(batch):problems.append({'error':'scope_mismatch'})
    if {g['slug'] for g in catalog}!={r['slug'] for r in inventory} or len(inventory)!=len(catalog):problems.append({'error':'inventory_incomplete'})
    expected=set()
    for item in inventory:
        try:
            controls=controls_from_native(parse_xml(item['init']))
            order=lambda x:(x['mode'],x.get('variant',''))
            if sorted(controls.values(),key=order)!=sorted(item['controls'],key=order):raise ValueError('inventory_controls_changed')
            expected.update(item['slug']+'--'+c['mode']+('--variant-'+c['variant'] if c.get('variant') else '') for c in controls.values())
        except Exception as error:problems.append({'slug':item['slug'],'error':str(error)})
    if expected!={r['case'] for r in rows} or len(rows)!=len(expected):problems.append({'error':'coverage_incomplete','missing':sorted(expected-{r['case'] for r in rows})})
    for row in rows:
        try:
            doc=read(FOLDER/'traces'/(row['case']+'.json'),{})
            if doc.get('summary')!=row:raise ValueError('trace_summary_changed')
            game=next(g for g in catalog if g['slug']==row['slug'])
            if doc['game']!=game:raise ValueError('catalog_identity_changed')
            inv=next(i for i in inventory if i['slug']==row['slug'])
            initialization=doc['trace'][0]['response']
            if doc.get('campaign'):
                import re
                if not re.fullmatch('[a-f0-9]{32}',doc['campaign']):raise ValueError('campaign_path')
                initialization=read(ROOT/'elk/boss-campaigns'/doc['campaign']/'initialization.json',{})['trace'][0]['response']
            if controls_from_native(parse_xml(initialization))!=controls_from_native(parse_xml(inv['init'])):raise ValueError('per_case_inventory_changed')
            passed.append(audit_case(doc))
        except Exception as error:problems.append({'case':row['case'],'error':str(error)})
    proof=read(FOLDER/'prior-providers-proof.json',{})
    if set(proof)!={str(p.relative_to(ROOT)) for p in prior_paths(batch)}:problems.append({'error':'previous_provider_proof_missing'})
    for name,value in proof.items():
        if digest(ROOT/name)!=value:problems.append({'error':'previous_provider_modified','file':name})
    files=[FOLDER/name for name in ('catalog.json','inventory.json','rounds.json','prior-providers-proof.json')]+[FOLDER/'traces'/(r['case']+'.json') for r in rows]
    files+=[ROOT/name for name in ('elk_audit.py','elk_client.py','elk_import.py','elk_protocol.py','elk_run.py','elk_reconcile.py','elk_paths.py','elk/catalog.json','elk/sources.json')]
    files.append(FOLDER/'blocked-variants.json')
    campaigns={read(FOLDER/'traces'/(r['case']+'.json'),{}).get('campaign') for r in rows}-{None}
    for campaign in campaigns:
        import re
        if not re.fullmatch('[a-f0-9]{32}',campaign):continue
        source=ROOT/'elk/boss-campaigns'/campaign;files+=[source/'initialization.json',source/'status.json',*sorted((source/'rounds').glob('*.json'))]
    files+=[ROOT/'elk_boss_audit.py',ROOT/'elk_boss.py',ROOT/'elk_boss_publish.py']
    files+=list(FOLDER.glob('prior-providers-proof-before-boss-*.json'))+list(FOLDER.glob('boss-proof-update-*.json'))
    hashes={str(p.relative_to(ROOT)):digest(p) for p in files if p.exists()}
    verified={p['case'] for p in passed}
    result={'passed':not problems,'games':len(catalog),'unique_demo_ids':len({g['id'] for g in catalog}),'normal_cases':sum(r['kind']=='normal' and r['case'] in verified for r in rows),'non_normal_cases':sum(r['kind']!='normal' and r['case'] in verified for r in rows),'expected_cases':len(expected),'verified_cases':len(passed),'native_results':sum(p['native_results'] for p in passed),'shared_demo_fiches':[g for g in catalog if g.get('shared_demo_with')],'problems':problems,'case_results':passed,'input_hashes':hashes}
    result.update(games_with_normal=len({r['slug'] for r in rows if r['case'] in verified and r['mode']=='DEF'}),normal_variant_cases=sum(r['case'] in verified and r['mode']=='DEF' for r in rows),xiter_cases=sum(r['case'] in verified and r['mode']!='DEF' for r in rows),expected_xiter_cases=sum(c['mode']!='DEF' for item in inventory for c in item['controls']),pending_cases=[{'case':r['case'],'reason':r.get('error'),'http_statuses':[s.get('http_status') for s in read(FOLDER/'traces'/(r['case']+'.json'),{}).get('trace',[])]} for r in rows if r['case'] not in verified])
    write_json(FOLDER/'audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('case_results','input_hashes','shared_demo_fiches','problems')}));print(json.dumps(problems[:12]))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=list(BATCHES),default='1-100');args=parser.parse_args();audit(args.batch)
