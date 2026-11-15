"""GO CRAPS: one Pass Line placement, then only rolls of that same active bet."""
from decimal import Decimal
from urllib.parse import unquote_plus
import json,re
from playngo_client import Playngo
from playngo_rules import latest
from playngo_run import ROOT,FOLDER,read,source_bundle
from endorphina_run import write_json

def table_profile(initial,xml):
    chips=latest(initial,54);limits=latest(initial,53)
    if not chips or not limits:raise ValueError('native_table_limits_missing')
    count=int(chips[0]);native=list(map(int,chips[1:1+count]))
    display=re.findall(r'<denom\s+Value="([\d.]+)"',xml)
    if len(display)!=count:raise ValueError('table_chip_pairing_missing')
    scales={Decimal(v)/Decimal(d) for v,d in zip(native,display)}
    if len(scales)!=1:raise ValueError('table_currency_scale_not_verified')
    scale=next(iter(scales));minimum=min(native)
    xmlmin=re.search(r'<Total\s+Min="([\d.]+)"',xml)
    if scale!=scale.to_integral_value() or not xmlmin or Decimal(xmlmin[1])*scale!=minimum or int(limits[1])!=minimum:raise ValueError('table_minimum_not_verified')
    return {'type':'craps_pass_line','bet_id':0,'cost_native':minimum,'scale':int(scale),'chips_native':native,'chips_display':display}

def roll_result(items):
    if any(code in (110,111) for code,args in items):raise ValueError('native_table_error')
    answer=latest(items,1);end=latest(items,3);wallet=latest(items,52)
    if not answer or not end or len(end)<2:raise ValueError('incomplete_table_roll')
    dice_count=int(answer[0]);count=int(answer[1+dice_count]);start=2+dice_count;pairs=answer[start:start+2*count]
    # Official kv.onServerSpin reads exactly N pairs; preserve, but do not interpret, its unread tail.
    if len(pairs)!=2*count:raise ValueError('table_bet_count_mismatch')
    active={int(pairs[i]):int(pairs[i+1]) for i in range(0,len(pairs),2)}
    if set(active)-{0}:raise ValueError('unexpected_active_table_bet')
    payout=0
    for code,args in items:
        if code!=2:continue
        kind=int(args[0]);n=int(args[1]);values=args[2:]
        if kind==2:
            if n:raise ValueError('unrecognized_table_transfer')
            continue
        if kind not in (0,1) or len(values)!=n*2:raise ValueError('unrecognized_table_feature')
        for i in range(0,len(values),2):
            bet=int(values[i]);value=int(values[i+1])
            if bet!=0:raise ValueError('unexpected_table_feature_bet')
            if kind==0:payout+=value
            else:active.pop(bet,None)
    win=int(end[1])
    if win!=payout:raise ValueError('table_payout_crosscheck_failed')
    return {'dice':list(map(int,answer[1:1+dice_count])),'active':active,'win':win,'wallet':wallet,'unread_native_fields':answer[start+2*count:],'closed':not active and bool(wallet and wallet[1]=='0')}

def verify_table(doc):
    from playngo_table_rules import transcript_errors
    errors=transcript_errors(doc['trace']);summary=doc['summary'];trace=doc['trace'];initial=[];rolls=[]
    for step in trace:
        if step.get('status')!='received':errors.append('uncertain_table_request')
        if any(c['code']==1 for c in step.get('commands',[])):rolls.append(step)
        elif not rolls:initial+=step.get('responses',[])
        elif step.get('commands'):errors.append('unexpected_table_continuation_command')
    try:
        config=table_profile([(x['code'],x['args']) for x in initial],doc['settings_xml'])
        before=int(next(x['args'][0] for x in reversed(initial) if x['code']==52));wins=0
        if not rolls:raise ValueError('table_entry_missing')
        closed=False
        for index,step in enumerate(rolls):
            if closed:raise ValueError('table_roll_after_settlement')
            expected=['1','0',str(config['cost_native']),'0'] if index==0 else ['0','0']
            if step['commands']!=[{'code':1,'args':expected}]:raise ValueError('additional_or_unverified_table_stake')
            result=roll_result([(x['code'],x['args']) for x in step['responses']]);wins+=result['win'];closed=result['closed']
            if result['active'] and result['active']!={0:config['cost_native']}:raise ValueError('unexpected_active_table_value')
        if not closed:raise ValueError('table_bet_still_active')
        after=int(result['wallet'][0]);cost=config['cost_native']
        if before-cost+wins!=after:raise ValueError('table_wallet_mismatch')
        for key,value in [('cost_native',cost),('win_native',wins),('balance_before_native',before),('balance_after_native',after),('internal_spin_results',len(rolls))]:
            if summary.get(key)!=value:errors.append('table_summary_mismatch:'+key)
    except Exception as exc:errors.append(str(exc))
    return errors

def run():
    game=next(g for g in read(ROOT/'playngo/catalog.json') if g['id']=='716')
    path=FOLDER/'traces'/f"{game['case_slug']}--normal.json"
    previous=read(path,{})
    if previous.get('summary',{}).get('entry_sent'):return previous['summary']
    summary={'case':game['case_slug']+'--normal','id':game['id'],'slug':game['slug'],'name':game['name'],'kind':'normal','game_type':'craps','status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    def save(c):
        doc.update(authority=getattr(c,'authority',{}),trace=c.trace);write_json(path,doc)
    c=Playngo(game,save)
    try:
        c.bootstrap();c.connect();raw=c.configuration['settings'].removeprefix('&settings=');xml=unquote_plus(raw)
        initial=c.send('104 '+game['id']+' 0 %22'+raw+'%22')
        state=latest(initial,56);wallet=latest(initial,52)
        if latest(initial,104)!=['1'] or latest(initial,109) is None or not state or state[0:2]!=['0','0'] or state[2]!='0' or not wallet or wallet[1]!='0':raise ValueError('fresh_table_not_idle')
        source,proof=source_bundle(c,game);params=table_profile(initial,xml)
        # Saved public decoder identifies PASS=0 and onClientRoll(additions, removals, offMask).
        if 'onClientRoll' not in source or 'PASS' not in source:raise ValueError('table_public_converter_not_verified')
        doc.update(profile=params,profile_proof=proof,settings_xml=xml,mode_inventory={'type':'table','tested_bet':'Pass Line','other_bets':'not_exercised'})
        summary.update(entry_sent=True,cost_native=params['cost_native'],scale=params['scale'],balance_before_native=int(wallet[0]));save(c)
        command='1 1 0 '+str(params['cost_native'])+' 0';wins=0
        for index in range(100):
            received=c.send(command);result=roll_result(received);wins+=result['win']
            if result['closed']:break
            if not result['active']:raise ValueError('table_wallet_not_closed_no_further_roll_sent')
            command='1 0 0' # Same still-active Pass Line bet. Adds zero chips.
        else:raise ValueError('table_existing_bet_continuation_limit')
        after=int(result['wallet'][0])
        if summary['balance_before_native']-params['cost_native']+wins!=after:raise ValueError('table_wallet_mismatch')
        summary.update(status='completed',win_native=wins,balance_after_native=after,internal_spin_results=index+1,wallet_check='match')
        save(c)
    except Exception as exc:
        summary.update(status='needs_review',error=str(exc)[:300]);save(c)
    finally:c.close()
    write_json(FOLDER/'rounds.json',[read(p)['summary'] for p in FOLDER.joinpath('traces').glob('*.json') if read(p,{}).get('summary')])
    return summary
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=True))
