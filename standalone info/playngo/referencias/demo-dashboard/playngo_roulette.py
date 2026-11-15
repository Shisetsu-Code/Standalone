"""One minimum straight-zero bet, without rebet or guessed continuations."""
import json,re
from urllib.parse import unquote_plus
from playngo_client import Playngo
from playngo_rules import latest
from playngo_craps import table_profile
from playngo_run import ROOT,FOLDER,read,source_bundle
from endorphina_run import write_json

def profile(initial,xml,source):
    data=table_profile(initial,xml)
    limits=latest(initial,53)
    if limits[0]!='6' or any(int(limits[i])!=data['cost_native'] for i in (1,3,5)):raise ValueError('roulette_minimum_limits_not_verified')
    zero=re.search(r'case 150:return\{position:\w+,type:0,index:0,seatIdx:0,betIdx:0,contains:\[0\],payout:([\w$]+)\.TYPE_PAYOUTS\[0\]\}',source)
    if not zero or not re.search(re.escape(zero[1])+r'\.TYPE_PAYOUTS=\[35,',source):raise ValueError('roulette_zero_payout_not_verified')
    if '.CLIENT_SPIN=1' not in source:raise ValueError('roulette_spin_opcode_not_verified')
    return dict(data,type='roulette_zero',bet_id=150,payout_profit=35,source_excerpt=zero.group(0))

def result(items,cost,bonus_before):
    if any(code in (110,111) for code,args in items):raise ValueError('native_roulette_error')
    spin=latest(items,1);wallet=latest(items,52)
    if not spin or len(spin)<4 or not wallet or wallet[1]!='0':raise ValueError('roulette_not_closed_no_continuation_sent')
    if int(wallet[2] if len(wallet)>2 else 0)!=bonus_before:raise ValueError('roulette_bonus_balance_changed')
    outcome,total_bet,total_win,count=map(int,spin[:4]);pairs=spin[4:4+2*count]
    if not 0<=outcome<=36 or total_bet!=cost or len(pairs)!=2*count:raise ValueError('roulette_native_result_mismatch')
    expected=cost*36 if outcome==0 else 0
    if total_win!=expected:raise ValueError('roulette_gross_return_mismatch')
    expected_pairs=['150',str(cost)] if outcome==0 else []
    if pairs!=expected_pairs:raise ValueError('roulette_winning_position_mismatch')
    return {'outcome':outcome,'win':total_win,'balance_after_native':int(wallet[0]),'unread_native_fields':spin[4+2*count:]}

def verify_roulette(doc):
    from playngo_table_rules import transcript_errors
    errors=transcript_errors(doc['trace']);initial=[];entries=[]
    try:
        for step in doc['trace']:
            if step.get('status')!='received':errors.append('uncertain_roulette_request')
            sent=step.get('commands',[])
            if any(x['code']==1 for x in sent):entries.append(step)
            elif entries and sent:errors.append('unexpected_roulette_continuation')
            else:initial+=step.get('responses',[])
        if len(entries)!=1:raise ValueError('not_exactly_one_roulette_entry')
        proof=doc['profile_proof'];source=ROOT/proof['file']
        params=profile([(x['code'],x['args']) for x in initial],doc['settings_xml'],source.read_text(encoding='utf8'))
        cost=params['cost_native']
        if entries[0]['commands']!=[{'code':1,'args':['1','150',str(cost)]}]:raise ValueError('unverified_or_additional_roulette_stake')
        before=next(x['args'] for x in reversed(initial) if x['code']==52)
        native=result([(x['code'],x['args']) for x in entries[0]['responses']],cost,int(before[2] if len(before)>2 else 0))
        if before[1]!='0' or int(before[0])-cost+native['win']!=native['balance_after_native']:raise ValueError('roulette_wallet_mismatch')
        expected={'cost_native':cost,'scale':params['scale'],'win_native':native['win'],'balance_before_native':int(before[0]),'balance_after_native':native['balance_after_native'],'internal_spin_results':1}
        if any(doc['summary'].get(k)!=v for k,v in expected.items()):errors.append('roulette_summary_mismatch')
    except Exception as exc:errors.append(str(exc))
    return errors

def run():
    game=next(g for g in read(FOLDER/'catalog.json') if g['gid']=='europeanroulette')
    path=FOLDER/'traces'/f"{game['case_slug']}--normal.json";previous=read(path,{})
    if previous.get('summary',{}).get('entry_sent'):return previous['summary']
    summary={'case':game['case_slug']+'--normal','id':game['id'],'slug':game['slug'],'name':game['name'],'kind':'normal','game_type':'roulette','status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    def save(c):doc.update(authority=getattr(c,'authority',{}),trace=c.trace);write_json(path,doc)
    c=Playngo(game,save)
    try:
        c.bootstrap();c.connect();raw=c.configuration['settings'].removeprefix('&settings=');xml=unquote_plus(raw)
        initial=c.send('104 '+game['id']+' 0 %22'+raw+'%22');wallet=latest(initial,52)
        if latest(initial,104)!=['1'] or latest(initial,109) is None or not wallet or wallet[1]!='0':raise ValueError('fresh_roulette_not_idle')
        source,proof=source_bundle(c,game);params=profile(initial,xml,source)
        doc.update(profile=params,profile_proof=proof,settings_xml=xml,mode_inventory={'type':'table','tested_bet':'Straight zero','other_bets':'not_exercised'})
        summary.update(entry_sent=True,cost_native=params['cost_native'],scale=params['scale'],balance_before_native=int(wallet[0]));save(c)
        received=c.send('1 1 150 '+str(params['cost_native']));native=result(received,params['cost_native'],int(wallet[2] if len(wallet)>2 else 0))
        if summary['balance_before_native']-params['cost_native']+native['win']!=native['balance_after_native']:raise ValueError('roulette_wallet_mismatch')
        doc['table_results']=[native];summary.update(status='completed',win_native=native['win'],balance_after_native=native['balance_after_native'],internal_spin_results=1,wallet_check='match');save(c)
    except Exception as exc:summary.update(status='needs_review',error=str(exc)[:300]);save(c)
    finally:c.close()
    write_json(FOLDER/'rounds.json',[read(p)['summary'] for p in FOLDER.joinpath('traces').glob('*.json') if read(p,{}).get('summary')]);return summary
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
