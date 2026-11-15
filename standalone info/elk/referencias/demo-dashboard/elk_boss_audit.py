"""Independent native ledger and progress audit for Pirots 5 campaigns."""
import argparse,hashlib,json,re
from decimal import Decimal as D
from pathlib import Path
import xml.etree.ElementTree as ET
from elk_protocol import parse_xml,redact_xml
from elk_audit import controls_from_native
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent
CACHE={}

def read(path):return json.loads(path.read_text(encoding='utf8'))
def masks(text):
    root=parse_xml(text);result={}
    for world in ('temple','ship','nest'):
        raw=root.findtext("VAR[@id='collected-tokens-"+world+"']/STATE")
        if raw is None or not re.fullmatch('[0-7]',raw):raise ValueError('native_token_state')
        result[world]=int(raw)
    return result

def terminal_counters(node):
    for counter in node.findall('COUNTERS/COUNTER'):
        if counter.get('name') not in ('bonus-counter','free-spins','respins','lives','coin-game-counter') or D(counter.get('left','0'))!=0:raise ValueError('native_bonus_finished')

def verify_target(document):
    campaign=document['campaign'];sequence=document['campaign_sequence']
    if campaign not in CACHE:CACHE[campaign]=audit(campaign,publish=False)
    report=CACHE[campaign]
    if not report['passed']:raise ValueError('boss_campaign_not_verified')
    entry=next((r for r in report['verified'] if r['sequence']==sequence and r['kind']=='boss'),None)
    if entry is None:raise ValueError('boss_campaign_case_missing')
    source=read(ROOT/'elk/boss-campaigns'/campaign/'rounds'/('%05d.json'%sequence));row=document['summary']
    if document['trace']!=source['trace'] or document['results']!=source['results'] or row['control']!=entry['control']:raise ValueError('boss_case_source_changed')
    if row['id']!='10266' or row['slug']!='pirots-5' or row['mode']!=entry['control']['mode'] or row['case']!='pirots-5--'+row['mode']+'--variant-boss':raise ValueError('boss_case_identity')
    if row['kind']!=('normal' if row['mode']=='DEF' else 'purchase') or row['status']!='completed':raise ValueError('boss_case_kind')
    for field in ('cost','win','balance_before','balance_after','wallet_check','closed','round_id','native_results'):
        if row[field]!=entry[field]:raise ValueError('boss_native_financial_summary:'+field)
    return {'case':row['case'],'passed':True,'native_results':entry['native_results']}

def audit(campaign,publish=True):
    if not re.fullmatch('[a-f0-9]{32}',campaign):raise ValueError('campaign_path')
    folder=ROOT/'elk/boss-campaigns'/campaign;status=read(folder/'status.json');initial=read(folder/'initialization.json');problems=[];verified=[];boss=[]
    def require(ok,error):
        if not ok:raise ValueError(error)
    try:
        launch=initial['launch'];require(launch['gameid']=='10266' and launch['mode']=='demo' and launch['operatorid']=='44' and launch['currency']=='EUR' and launch['capi']=='https://gc5-stage.contentmedia.eu/capi','official_demo_scope')
        require(len(initial['trace'])==1 and initial['trace'][0]['method']=='init','one_native_init')
        first=initial['trace'][0];require(first['status']=='received' and first['http_status']==200,'successful_init');init=parse_xml(first['response'])
        require(init.findtext('method')=='init' and init.findtext('errorcode')=='0' and init.findtext('roundid')=='0' and D(init.findtext('gamesession/totbet'))==0 and D(init.findtext('gamesession/totwon'))==0,'fresh_initial_session')
        controls=controls_from_native(init);before=init;state=masks(init.findtext('variants/pubstate/init'));require(all(v==0 for v in state.values()),'no_preloaded_progress')
        seen_rounds=set();seen_requests={first['request_id']}
        for number,row in enumerate(status['rounds'],1):
            document=read(folder/'rounds'/('%05d.json'%number));trace=document['trace'];control=document['control'];summary=document['summary']
            require(document['sequence']==row['sequence']==number and document['status']=='completed','native_sequence')
            require(control==controls[control['mode']+'@'+control['variant']],'published_native_control')
            require(len(trace)==2 and [t['method'] for t in trace]==['purchase','checkwin'],'one_purchase_then_check')
            for step in trace:
                require(step['http_status']==200 and step['status']=='received','native_transport')
                require(step['request_id'] not in seen_requests,'unique_transport_id');seen_requests.add(step['request_id'])
                require(redact_xml(step['request'])==step['request'] and redact_xml(step['response'])==step['response'],'private_identifiers_removed')
            request,check_request=[parse_xml(t['request']) for t in trace];buy,check=[parse_xml(t['response']) for t in trace]
            require(set(request.attrib)<={'gamesession','amount','cur','bmode','betdetails','betlevel','pmode','orientation','sound','monetaryunit','gamespeed','variant'} and request.get('betdetails')=='','no_state_overrides')
            require(request.get('bmode')==control['mode'] and request.get('variant')==control['variant'] and request.get('betlevel')==control['betlevel'] and D(request.get('amount'))==D(control['amount']) and request.get('cur')=='EUR','native_entry_request')
            require(document['progress_before']==state,'native_progress_before')
            kind=document['kind'];require(kind in ('progression','boss') and kind==row['kind'],'campaign_case_kind')
            if kind=='boss':require(control['variant']=='boss' and all(v==7 for v in state.values()),'boss_unlocked_natively')
            else:require(control['variant'] in ('temple','ship','nest'),'published_non_boss_progression')
            require(buy.findtext('method')=='purchase' and check.findtext('method')=='checkwin','native_methods')
            require(all(r.findtext('errorcode')=='0' and r.findtext('player/currency')=='EUR' for r in (before,buy,check)),'native_acceptance')
            info=buy.find('roundinfo');rid=buy.findtext('roundid')
            require(bool(rid) and rid.startswith('round-') and rid not in seen_rounds and rid==info.findtext('roundid')==check.findtext('roundid')==check_request.get('roundid'),'native_round_correlation');seen_rounds.add(rid)
            cost=D(info.findtext('betamount'));win=D(info.findtext('winamount'));balance=D(before.findtext('player/balance'));after=D(check.findtext('player/balance'))
            require(info.findtext('currency')=='EUR' and info.findtext('bmode')==control['mode'] and info.findtext('betlevel')==control['betlevel'],'native_round_control')
            require(cost==D(control['amount']) and win>=0 and balance>=cost and balance-cost+win==after==D(info.findtext('balanceafterwin')),'exact_incremental_wallet')
            require(D(before.findtext('gamesession/totbet'))+cost==D(check.findtext('gamesession/totbet')) and D(before.findtext('gamesession/totwon'))+win==D(check.findtext('gamesession/totwon')),'exact_cumulative_totals')
            require(D(check.findtext('gamesession/netposition'))==D(check.findtext('gamesession/totwon'))-D(check.findtext('gamesession/totbet')),'native_netposition')
            pub=parse_xml(buy.findtext('game/pubdata'));purchases=pub.findall('PURCHASE');require(pub.tag=='PURCHASES' and len(purchases)==1,'one_native_purchase');purchase=purchases[0]
            require(purchase.get('variant')==control['variant'] and purchase.get('bmode')==control['mode'] and purchase.get('betlevel')==control['betlevel'] and D(purchase.get('betamount'))==cost and D(purchase.get('winamount'))==win,'native_pubdata_money')
            nodes=purchase.findall('RESULT');table=parse_xml(next(v for v in init.findall('variants/variant') if v.get('id')==control['variant']).findtext('game/paytable'));allowed={n.get('name') for n in table.findall('MODE')}
            require(bool(nodes) and len(nodes)==len(purchase) and all(n.get('mode') in allowed for n in nodes),'published_result_modes')
            require([n.get('resultIndex') for n in nodes]==[str(i) for i in range(len(nodes))],'all_result_indices')
            require(D(nodes[-1].get('amounttotal'))==win,'terminal_native_total')
            terminal_counters(nodes[-1])
            expected_steps=[{'step':i,'mode':n.get('mode'),'attributes':dict(n.attrib),'xml':ET.tostring(n,encoding='unicode')} for i,n in enumerate(nodes)]
            require(document['results']==expected_steps and summary['native_results']==len(nodes),'all_native_steps_preserved')
            financial={'cost':str(cost),'win':str(win),'balance_before':str(balance),'balance_after':str(after),'wallet_check':'match','closed':True,'round_id':rid,'native_results':len(nodes)}
            require(summary==financial and row=={'sequence':number,'kind':kind,'control':control,**financial},'saved_financial_summary')
            state=masks(buy.findtext('game/pubstate/roundend'));require(document['progress_after']==state,'native_progress_after')
            verified.append({'sequence':number,'kind':kind,'control':control,**financial})
            if kind=='boss':boss.append({'mode':control['mode'],'sequence':number})
            before=check
        require(status['boss_cases']==boss,'boss_manifest_matches')
        require(status['status']=='completed' and {r['mode'] for r in boss}=={'DEF','X01','X02','X03','X04','X05'} and len(boss)==6,'all_six_boss_modes_completed')
    except Exception as error:problems.append(str(error))
    files=[folder/'status.json',folder/'initialization.json',*sorted((folder/'rounds').glob('*.json'))]
    files+=[ROOT/name for name in ('elk_boss.py','elk_boss_audit.py','elk_client.py','elk_protocol.py')]
    output={'campaign':campaign,'passed':not problems,'verified_rounds':len(verified),'progression_rounds':sum(r['kind']=='progression' for r in verified),'boss_cases':boss,'native_results':sum(r['native_results'] for r in verified),'problems':problems,'verified':verified,'input_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    if publish:write_json(folder/'audit.json',output)
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('campaign');args=parser.parse_args();report=audit(args.campaign);print(json.dumps({k:v for k,v in report.items() if k not in ('verified','input_hashes')}))
