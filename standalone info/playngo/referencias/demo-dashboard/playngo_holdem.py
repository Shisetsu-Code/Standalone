"""3-Hand Hold'em sample: one occupied seat, minimum ante, no AA, Fold."""
import json,re
from decimal import Decimal
from urllib.parse import unquote_plus
from playngo_client import Playngo
from playngo_rules import latest
from playngo_run import ROOT,FOLDER,read,source_bundle
from endorphina_run import write_json

def profile(initial,xml,source):
    chips=latest(initial,54);limits=latest(initial,53)
    if not chips or not limits or limits[0]!='4':raise ValueError('holdem_limits_missing')
    count=int(chips[0]);values=list(map(int,chips[1:1+count]));display=re.findall(r'<denom\s+Value="([\d.]+)"',xml)
    if len(display)!=count or not values or min(values)<=0:raise ValueError('holdem_chip_pairing_missing')
    scales={Decimal(v)/Decimal(d) for v,d in zip(values,display)}
    if len(scales)!=1:raise ValueError('holdem_currency_scale_not_verified')
    scale=next(iter(scales));ante=re.search(r'<Ante\s+Min="([\d.]+)"',xml);minimum=min(values)
    if scale!=scale.to_integral_value() or not ante or Decimal(ante[1])*scale!=minimum or int(limits[1])!=minimum:raise ValueError('holdem_minimum_not_verified')
    if not all(token in source for token in ('.SEAT_CNT=3','.FOLD=0','.DEAL=1','.PLAY=2','.TURN=5')):raise ValueError('holdem_public_schema_not_verified')
    return {'type':'holdem_single_seat_fold','seat':0,'cost_native':minimum,'scale':int(scale),'chips_native':values,'chips_display':display,'aa_native':0,'call_native':0}

def deal_result(items,cost):
    if any(code in (110,111) for code,args in items):raise ValueError('native_holdem_deal_error')
    deal=latest(items,1);turn=latest(items,5)
    if any(code==52 and len(args)>1 and args[1]=='0' for code,args in items):raise ValueError('holdem_deal_already_closed_no_fold_sent')
    if not deal or len(deal)<22 or deal[0]!='3':raise ValueError('holdem_deal_not_complete')
    for seat in range(3):
        start=1+seat*6;ante=int(deal[start]);aa=int(deal[start+1])
        if ante!=(cost if seat==0 else 0) or aa!=0:raise ValueError('holdem_unexpected_seat_or_aa_stake')
    if not turn or turn[0]!='0':raise ValueError('holdem_expected_turn_not_received')
    return {'ante_native':cost,'seat':0,'community':deal[19:22],'seat_cards':deal[3:5]}

def fold_result(items,before,bonus_before,cost):
    if any(code in (110,111) for code,args in items):raise ValueError('native_holdem_fold_error')
    answer=latest(items,2);outcome=latest(items,3);wallet=latest(items,52)
    if not answer or answer[:3]!=['0','0','0']:raise ValueError('holdem_unexpected_call_or_aa')
    if not outcome or len(outcome)<25:raise ValueError('holdem_outcome_missing')
    for seat in range(3):
        start=1+seat*8
        if int(outcome[start+1])!=0 or int(outcome[start+2])!=0:raise ValueError('holdem_unexpected_fold_payout')
    if not wallet or wallet[1]!='0' or int(wallet[0])!=before-cost or int(wallet[2] if len(wallet)>2 else 0)!=bonus_before:raise ValueError('holdem_fold_wallet_not_closed')
    return {'balance_after_native':int(wallet[0]),'win_native':0,'outcome_native':outcome,'action':'Fold','seat':0}

def verify_holdem(doc):
    from playngo_table_rules import transcript_errors
    errors=transcript_errors(doc['trace']);initial=[];gaming=[]
    try:
        for step in doc['trace']:
            if step.get('status')!='received':errors.append('uncertain_holdem_request')
            sent=step.get('commands',[])
            if any(x['code'] in (1,2) for x in sent):gaming.append(step)
            elif gaming and sent:errors.append('unexpected_holdem_continuation')
            else:initial+=step.get('responses',[])
        if len(gaming)!=2:raise ValueError('holdem_not_one_deal_and_one_fold')
        source=ROOT/doc['profile_proof']['file'];params=profile([(x['code'],x['args']) for x in initial],doc['settings_xml'],source.read_text(encoding='utf8'));cost=params['cost_native']
        if gaming[0]['commands']!=[{'code':1,'args':['3',str(cost),'0','0','0','0','0']}]:raise ValueError('holdem_deal_parameters_mismatch')
        if gaming[1]['commands']!=[{'code':2,'args':['0','0']}]:raise ValueError('holdem_additional_call_or_unverified_action')
        deal_result([(x['code'],x['args']) for x in gaming[0]['responses']],cost)
        wallet=next(x['args'] for x in reversed(initial) if x['code']==52)
        if wallet[1]!='0':raise ValueError('holdem_initial_not_idle')
        native=fold_result([(x['code'],x['args']) for x in gaming[1]['responses']],int(wallet[0]),int(wallet[2] if len(wallet)>2 else 0),cost)
        expected={'cost_native':cost,'scale':params['scale'],'win_native':0,'balance_before_native':int(wallet[0]),'balance_after_native':native['balance_after_native'],'internal_spin_results':1}
        if any(doc['summary'].get(k)!=v for k,v in expected.items()):errors.append('holdem_summary_mismatch')
    except Exception as exc:errors.append(str(exc))
    return errors

def run():
    game=next(g for g in read(FOLDER/'catalog.json') if g['gid']=='threehandholdem');path=FOLDER/'traces'/f"{game['case_slug']}--normal.json"
    previous=read(path,{})
    if previous.get('summary',{}).get('entry_sent'):return previous['summary']
    summary={'case':game['case_slug']+'--normal','id':game['id'],'slug':game['slug'],'name':game['name'],'kind':'normal','game_type':'holdem','variant':'Single seat · minimum ante · no AA · Fold','status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    def save(c):doc.update(authority=getattr(c,'authority',{}),trace=c.trace);write_json(path,doc)
    c=Playngo(game,save)
    try:
        c.bootstrap();c.connect();raw=c.configuration['settings'].removeprefix('&settings=');xml=unquote_plus(raw);initial=c.send('104 '+game['id']+' 0 %22'+raw+'%22');wallet=latest(initial,52)
        if latest(initial,104)!=['1'] or latest(initial,109) is None or not wallet or wallet[1]!='0':raise ValueError('fresh_holdem_not_idle')
        source,proof=source_bundle(c,game);params=profile(initial,xml,source);cost=params['cost_native']
        doc.update(profile=params,profile_proof=proof,settings_xml=xml,mode_inventory={'type':'table','tested_branch':'One seat, minimum ante, no AA, Fold','call_and_showdown':'not_exercised'})
        summary.update(entry_sent=True,cost_native=cost,scale=params['scale'],balance_before_native=int(wallet[0]));save(c)
        deal=c.send('1 3 '+str(cost)+' 0 0 0 0 0');dealt=deal_result(deal,cost);doc['dealt']=dealt;save(c)
        received=c.send('2 0 0');native=fold_result(received,int(wallet[0]),int(wallet[2] if len(wallet)>2 else 0),cost)
        doc['table_results']=[native];summary.update(status='completed',win_native=0,balance_after_native=native['balance_after_native'],internal_spin_results=1,wallet_check='match');save(c)
    except Exception as exc:summary.update(status='needs_review',error=str(exc)[:300]);save(c)
    finally:c.close()
    write_json(FOLDER/'rounds.json',[read(p)['summary'] for p in FOLDER.joinpath('traces').glob('*.json') if read(p,{}).get('summary')]);return summary
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
