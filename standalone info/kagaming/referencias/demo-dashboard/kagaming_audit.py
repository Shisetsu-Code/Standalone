"""Read-only verification against native wallet fields and source-bound prices."""
import json,hashlib
from pathlib import Path
from kagaming_client import minimum_profile,mode_profiles,position_for_step,save
from kagaming_layout import batch_folder,scope_policy,is_excluded
ROOT=Path(__file__).resolve().parent
BATCH=batch_folder()


class _Inventory:
    """One audit-run snapshot of planning inputs; never stores case results."""
    def __init__(self,common_source):
        self.common_sha256=hashlib.sha256(common_source).hexdigest()
        self._inputs={};self._profiles={}

    def inputs(self,gid):
        if gid not in self._inputs:
            source=(ROOT/'kagaming/reference'/(gid.lower()+'.js')).read_bytes().decode('utf8')
            init=json.loads((BATCH/'initializations'/(gid+'.json')).read_bytes())
            self._inputs[gid]=(init,source)
        return self._inputs[gid]

    def profiles(self,gid,init,source,buy_feature):
        # Recompute the key from the supplied inputs even for an existing
        # context: changed source/runtime values cannot reuse an inventory.
        canonical=json.dumps(init,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        key=(gid,hashlib.sha256(source.encode('utf8')).hexdigest(),
             hashlib.sha256(canonical.encode('utf8')).hexdigest(),self.common_sha256,buy_feature)
        if key not in self._profiles:
            self._profiles[key]=mode_profiles(init,source,buy_feature)
        return self._profiles[key]


def audit_case(case,initialization=None,source_text=None,*,private_inventory=None):
    if case.get('native_recovery'):
        from kagaming_recovery import audit_recovered
        return audit_recovered(case,root=BATCH)
    try:
        gid=case['game']
        if private_inventory is not None and not isinstance(private_inventory,_Inventory):raise ValueError('invalid_private_inventory_context')
        if private_inventory is not None and (initialization is None or source_text is None):
            saved_init,saved_source=private_inventory.inputs(gid)
            init=saved_init if initialization is None else initialization
            source=saved_source if source_text is None else source_text
        else:
            source=source_text if source_text is not None else (ROOT/'kagaming/reference'/(gid.lower()+'.js')).read_text(encoding='utf8')
            init=initialization if initialization is not None else json.loads((BATCH/'initializations'/(gid+'.json')).read_text(encoding='utf8'))
        profiles=mode_profiles(init,source,case['mode']=='buy') if private_inventory is None else private_inventory.profiles(gid,init,source,case['mode']=='buy')
        base=profiles[0]
        mode_key=case.get('profile',{}).get('key')
        mode=next(p for p in profiles if p['kind']==case['mode'] and p.get('atb',0)==case.get('atb',0) and (p['key']==mode_key if mode_key else True))
        expected=mode['cost_native']
        assert case['cost_native']==expected and case['profile']['cost_native']==expected,'source cost differs'
        assert case['profile']['source_sha256']==hashlib.sha256(source.encode('utf8')).hexdigest(),'source changed'
        special=None
        from kagaming_bonus_pick import is_supported
        if gid=='PenaltyShootout':
            from kagaming_penalty import reconcile_round
            special=reconcile_round(mode,case['steps'],case['balance_before_native'])
        elif gid in ('HomeRunDerby','BonusPoker','ChickenQuest','PhilosopherRoulette'):
            if gid=='PhilosopherRoulette':
                from kagaming_philosopher import reconcile_round
            elif gid=='ChickenQuest':
                from kagaming_chicken import reconcile_round
            else:
                from kagaming_interactive import reconcile_round
            special=reconcile_round(mode,case['steps'],case['balance_before_native'])
            special={'balance_before_native':special['wallet_before'],'cost_native':special['debit_native'],'win_native':special['win_native'],'balance_after_native':special['wallet_after'],'internal_steps':len(case['steps']),'wallet_check':'match'}
        elif is_supported(gid) and any(s.get('response',{}).get('md',{}).get('bpd') for s in case['steps']):
            from kagaming_bonus_pick import reconcile_round
            first=case['steps'][0]['request']
            assert first.get('gn')==gid and all(first.get(k)==mode[k] for k in ('sel','cps','dn','atb')) and first.get('pos')==position_for_step(mode),'special initial request differs from runtime profile'
            special=reconcile_round(case['balance_before_native'],expected,case['steps'],source,(ROOT/'kagaming/reference/game.min.2090.js').read_bytes())
        if special is not None:
            assert case['status']=='verified','not verified'
            first=case['steps'][0]['request']
            assert all(first.get(k)==mode[k] for k in ('sel','cps','dn','atb')),'special initial stake differs from runtime minimum'
            assert all(case.get(k)==special[k] for k in ('balance_before_native','cost_native','win_native','balance_after_native','internal_steps','wallet_check')),'special round summary mismatch'
            return {'game':gid,'mode':case['mode'],'atb':case.get('atb',0),'passed':True,'native_steps':len(case['steps']),'protocol':'source-bound decision ledger'}
        balance=case['balance_before_native'];credit=0;seen=set()
        assert case['status']=='verified' and case['steps'],'not verified'
        for i,step in enumerate(case['steps']):
            req=step['request'];r=step['response'];md=r['md'];cost=expected if i==0 else 0
            assert step['status']=='received' and step['http_status']==200 and r['e'] is False and r['ec']==0 and md['v'] is True,'native error'
            assert req['sid']==r['sid'] and req['sid'] not in seen,'request identity'
            seen.add(req['sid'])
            echo_fields=('cps','dn','atb') if gid in ('FrenchRoulette','AmericanRoulette') else ('sel','cps','dn','atb')
            assert all(req[k]==md[k] for k in echo_fields),'parameter echo'
            assert req['gn']==gid and req['sel']==mode['sel'] and req['cps']==mode['cps'] and req['dn']==mode['dn'],'changed stake'
            expected_atb=0 if i and base.get('purchase_via_atb') else case.get('atb',0)
            expected_position=position_for_step(mode,case['steps'][i-1]['response']['md'] if i else None)
            legacy_empty=gid=='Shopping' and i==0 and case.get('legacy_empty_initial_position') is True and req.get('pos') is None and md.get('sm',[None])[0]==0
            assert req['atb']==expected_atb and (req.get('pos')==expected_position or legacy_empty),'unreviewed mode'
            assert md['pbb']==balance and r['pcr']==balance-cost,'debit mismatch'
            assert r['cr']==r['pcr']+md['tw'] and md['obb']==r['cr'] and md['tw']>=0,'credit mismatch'
            if i:
                prior=case['steps'][i-1]['response']['md']
                pending=prior.get('fsr',0)>0
                if gid=='Shopping':pending=pending or prior.get('sm',[None])[0] not in (-1,3)
                assert pending and md['tid']==prior['tid'],'extra paid entry'
            balance=r['cr'];credit+=md['tw']
        last=case['steps'][-1]['response']['md']
        assert not last.get('fsr',0) and not last.get('rf',0) and not last.get('bpd'),'round pending'
        if gid=='Shopping':assert last.get('sm',[None])[0] in (-1,3),'shopping decision pending'
        if gid=='FortuneSkyLanterns':
            from kagaming_lanterns import assert_closed,validate_position
            assert_closed(last);validate_position(mode,case['steps'][0]['request'])
        if gid=='FrenchRoulette':
            from kagaming_roulette import assert_closed,validate_response
            assert_closed(last);validate_response(last,mode)
        if gid=='AmericanRoulette':
            from kagaming_american import assert_closed,validate_response,validate_position
            assert_closed(last);validate_response(last,mode);validate_position(mode,case['steps'][0]['request'])
        assert balance==case['balance_after_native'] and credit==case['win_native'],'summary mismatch'
        return {'game':gid,'mode':case['mode'],'atb':case.get('atb',0),'passed':True,'native_steps':len(case['steps'])}
    except Exception as error:return {'game':case.get('game'),'mode':case.get('mode'),'passed':False,'error':str(error)}

def run():
    results=[];inventory=None
    policy=scope_policy(BATCH);catalog_path=BATCH/'catalog.json'
    games=None;excluded=set()
    if catalog_path.exists():
        catalog=json.loads(catalog_path.read_bytes())
        games={game['id']:game for game in catalog}
        if len(games)!=len(catalog):raise ValueError('duplicate_audit_catalog_game')
        excluded={gid for gid,game in games.items() if is_excluded(game,policy)}
    elif policy.get('included_game_types') is not None:
        raise ValueError('included_audit_scope_requires_catalog')
    archival_cases=0
    for path in sorted((BATCH/'traces').glob('*.json')):
        raw=path.read_bytes();case=json.loads(raw)
        if case.get('status')=='verified':
            if games is not None:
                filename_game=next((gid for gid in sorted(games,key=len,reverse=True) if path.name.startswith(gid+'-')),None)
                if filename_game in excluded and case.get('game')==filename_game:
                    archival_cases+=1;continue
                if filename_game is None or case.get('game')!=filename_game:
                    results.append(dict(game=filename_game or case.get('game'),mode=case.get('mode'),
                                        passed=False,error='audit_catalog_filename_identity_mismatch',
                                        file=path.name,sha256=hashlib.sha256(raw).hexdigest()))
                    continue
            if not case.get('native_recovery') and inventory is None:
                inventory=_Inventory((ROOT/'kagaming/reference/game.min.2090.js').read_bytes())
            results.append(dict(audit_case(case,private_inventory=inventory),file=path.name,sha256=hashlib.sha256(raw).hexdigest()))
    result={'scope':'Recorded verified entries within the batch policy; coverage is checked separately',
            'passed':bool(results) and all(x['passed'] for x in results),'cases':results,
            'excluded_game_ids':sorted(excluded),'excluded_archival_cases':archival_cases}
    save(BATCH/'audit.json',result);return result

if __name__=='__main__':
    result=run();print(json.dumps({'passed':result['passed'],'verified_cases':len(result['cases'])}))
