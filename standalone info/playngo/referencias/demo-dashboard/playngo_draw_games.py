"""Source-bound wheel, single-hand poker, keno and three classic-slot samples."""
import json,re
import xml.etree.ElementTree as ET
from decimal import Decimal
from urllib.parse import unquote_plus
from playngo_rules import latest,profile as slot_profile
from playngo_run import ROOT,FOLDER,read,digest,source_bundle
from playngo_client import Playngo
from playngo_table_rules import transcript_errors
from endorphina_run import write_json

POKER={'jokerpoker','deuceswild','jacksorbetter'}
WHEELS={'superwheel','moneywheel'}
SIMPLE={'aceofspades','luckydiamonds','wildmelon'}
GAMES=POKER|WHEELS|SIMPLE|{'keno'}

def profile(game,initial,xml,source,configuration):
    gid=game['gid'];chips=latest(initial,54)
    if gid not in GAMES or not chips:raise ValueError('draw_game_not_supported')
    kind='poker' if gid in POKER else 'wheel' if gid in WHEELS else 'simple_slot' if gid in SIMPLE else 'keno'
    if kind=='poker':
        groups={};at=1
        for _ in range(int(chips[0])):
            hands,count=map(int,chips[at:at+2]);at+=2;groups[hands]=list(map(int,chips[at:at+count]));at+=count
        if at!=len(chips) or 1 not in groups:raise ValueError('poker_ragged_chips_invalid')
        public={int(s.attrib['Value']):[Decimal(x.attrib['Value']) for x in s.findall('denom')] for s in ET.fromstring(xml).findall('.//Set')}
        scales=set()
        if set(public)!=set(groups):raise ValueError('poker_denomination_groups_mismatch')
        for hands,values in groups.items():
            if len(values)!=len(public[hands]) or min(values)<=0:raise ValueError('poker_invalid_chip_pairing')
            scales.update(Decimal(v)/d for v,d in zip(values,public[hands]))
        denom=min(groups[1]);cost=denom;entry=f'1 1 {denom} 1';variant='One hand · one coin · replace all five cards · no gamble'
        tokens=['.DEAL=1','.DRAW=2','.COLLECT=3','String(t.coins),String(t.denom),String(t.hands)','t.holdMask&1<<']
    else:
        count=int(chips[0]);values=list(map(int,chips[1:count+1]));public=[Decimal(x.attrib['Value']) for x in ET.fromstring(xml).findall('.//denom')]
        if len(values)!=len(public) or not values or min(values)<=0:raise ValueError('draw_invalid_chip_pairing')
        scales={Decimal(v)/d for v,d in zip(values,public)};denom=min(values)
        if kind=='wheel':
            limits=latest(initial,53)
            if not limits or limits[0]!='4' or int(limits[1])!=denom or int(limits[3])!=denom:raise ValueError('wheel_minimum_not_verified')
            cost=denom;entry='1 '+str(cost)+' 0 0 0 0 0 0';variant='Minimum bet · first wheel position only'
            tokens=['.CSPIN=1','.SSPIN=1','r=new Array(7)','e.getInt(10)','t.bets[i].toString()']
        elif kind=='keno':
            cost=denom;entry=f'1 {cost} 1 2 1 2';variant='Minimum bet · numbers 1 and 2 · no gamble'
            tokens=['.SPINEND,[]','String(this._model.roundHandler.bet),String(1),String(e.length)','this._model.pickedNumbers']
            # Bind to the Keno converter and 80-number model, not the slot SDK.
            if not re.search(r'onSpin\(t\)\{var e=this\._model\.pickedNumbers',source):raise ValueError('keno_spin_binding_missing')
        else:
            p=slot_profile(source,initial,xml,configuration)
            if p['lines']!=1 or p['coins']!=1:raise ValueError('classic_slot_single_coin_not_verified')
            cost=p['cost_native'];entry=f"1 {p['coins']} {p['denomination']}"+(' 1' if latest(initial,83) is not None else '')
            variant='Minimum classic slot · coins/denomination wire format'
            tokens=['createLogicCommandConverter(){var t=this._config;new JA(','class JA extends Qy','[String(t.coins),String(t.denom)]','e.getInt(6)/e.getInt(1),s=e.getInt(6)']
    if len(scales)!=1 or next(iter(scales))!=int(next(iter(scales))):raise ValueError('draw_currency_scale_not_verified')
    if not all(t in source for t in tokens):raise ValueError('draw_public_schema_not_verified:'+kind)
    return {'type':kind,'cost_native':cost,'denomination':denom,'scale':int(next(iter(scales))),'entry_command':entry,'variant':variant}

def poker_draw(items):
    draw=latest(items,2)
    if draw is not None:
        if len(draw)<8:raise ValueError('poker_draw_shape_mismatch')
        return int(draw[6]),draw[7]=='1'
    draw=latest(items,6)
    if draw is not None:
        if len(draw)!=11 or draw[:3]!=['0','5','1']:raise ValueError('poker_not_one_unheld_hand')
        return int(draw[9]),draw[10]=='1'
    return None

def next_command(p,items):
    if any(c in (110,111) for c,a in items):raise ValueError('native_draw_error')
    wallet=latest(items,52)
    if wallet and wallet[1]=='0':return None
    kind=p['type']
    if kind=='poker':
        deal=latest(items,1)
        if deal is not None:
            if len(deal)<9 or deal[:2]!=['1',str(p['denomination'])] or deal[8]!='1':raise ValueError('poker_deal_not_one_hand')
            return '2 0 0 0 0 0'
        draw=poker_draw(items)
        if draw and draw[0]>0:return '3' if draw[1] else '52'
    elif kind=='keno':
        feature=latest(items,2)
        if feature is not None:
            if len(feature)!=24 or feature[0]!='0' or feature[3]!='20' or len(set(feature[4:]))!=20 or any(not 1<=int(x)<=80 for x in feature[4:]):raise ValueError('keno_draw_not_twenty_balls')
            echo=latest(items,1)
            if echo is not None and echo[:1]+echo[2:]!=[str(p['cost_native']),'2','1','2']:raise ValueError('keno_pick_echo_mismatch')
            return '3'
        end=latest(items,3)
        if end and len(end)>=5 and int(end[2])>0:return '4 0'
    elif kind=='simple_slot':
        result=latest(items,2)
        if result and len(result)==7 and int(result[6])>0:return '4 0'
    raise ValueError('unrecognized_draw_continuation')

def settlement(p,items,before,bonus):
    wallet=latest(items,52);kind=p['type'];cost=p['cost_native']
    if any(c in (110,111) for c,a in items):raise ValueError('native_draw_error')
    if not wallet or wallet[1]!='0' or int(wallet[2])!=bonus:raise ValueError('draw_wallet_not_closed')
    if kind=='wheel':
        result=latest(items,1)
        if not result or len(result)!=11 or result[3:10]!=[str(cost),'0','0','0','0','0','0']:raise ValueError('wheel_bet_echo_not_verified')
        win=int(result[10])
    elif kind=='simple_slot':
        result=latest(items,2)
        if not result or len(result)!=7 or result[:2]!=['1',str(p['denomination'])]:raise ValueError('classic_slot_result_not_verified')
        win=int(result[6])
    elif kind=='poker':
        draw=poker_draw(items)
        if draw is None:raise ValueError('poker_draw_result_missing')
        win=draw[0];collect=latest(items,3)
        if collect is not None and collect!=[str(win)]:raise ValueError('poker_collect_result_mismatch')
    elif kind=='keno':
        end=latest(items,3);feature=latest(items,2)
        # Native command.getInt(index, default=0) permits omitted trailing zeros.
        if end and len(end)<5:end=end+['0']*(5-len(end))
        if not end or len(end)!=5 or end[3]!='0' or not feature or feature[0]!='0' or int(feature[2])!=int(end[2]):raise ValueError('keno_final_result_mismatch')
        win=int(end[2])
    else:raise ValueError('unsupported_draw_game')
    if win<0 or before-cost+win!=int(wallet[0]):raise ValueError('draw_wallet_mismatch')
    return {'win_native':win,'balance_after_native':int(wallet[0])}

def verify_draw(doc):
    errors=transcript_errors(doc['trace'])
    try:
        initial=[];gaming=[];started=False
        for step in doc['trace']:
            if step.get('status')!='received':raise ValueError('uncertain_draw_request')
            if any(c['code']==1 for c in step.get('commands',[])):started=True
            (gaming if started else initial).append(step)
        initial_items=[(x['code'],x['args']) for s in initial for x in s.get('responses',[])]
        p=profile(doc['game'],initial_items,doc['settings_xml'],(ROOT/doc['profile_proof']['file']).read_text(encoding='utf8'),doc.get('public_bet_configuration'))
        if p!=doc['profile']:raise ValueError('draw_profile_mismatch')
        wallet=latest(initial_items,52)
        if not wallet or wallet[1]!='0':raise ValueError('draw_initial_not_idle')
        command=p['entry_command'];all_items=[]
        for step in gaming:
            parts=command.split() if command else []
            if not parts or step['commands']!=[{'code':int(parts[0]),'args':parts[1:]}]:raise ValueError('draw_command_mismatch')
            items=[(x['code'],x['args']) for x in step.get('responses',[])];all_items+=items;command=next_command(p,items)
        if not gaming or command is not None:raise ValueError('draw_not_complete')
        native=settlement(p,all_items,int(wallet[0]),int(wallet[2]));expected=dict(native,cost_native=p['cost_native'],scale=p['scale'],balance_before_native=int(wallet[0]),internal_spin_results=1)
        if any(doc['summary'].get(k)!=v for k,v in expected.items()):raise ValueError('draw_summary_mismatch')
        for attempt in doc.get('previous_attempts',[]):
            if digest(FOLDER/attempt['file'])!=attempt['sha256']:raise ValueError('rejected_draw_attempt_not_preserved')
            archived=read(FOLDER/attempt['file'])
            if attempt.get('status')=='accepted_partial_not_completed':
                if not restart_allowed(archived):raise ValueError('partial_deal_restart_not_proven')
            elif attempt.get('status') in (None,'rejected'):
                if not simple_rejection_allowed(archived):raise ValueError('classic_slot_rejection_not_proven')
            else:raise ValueError('unrecognized_draw_attempt_history')
    except Exception as exc:errors.append(str(exc))
    return errors

def restart_allowed(doc):
    if doc.get('game',{}).get('gid') not in POKER or doc.get('authority',{}).get('practice')!=1 or doc.get('authority',{}).get('demo')!=2 or doc.get('authority',{}).get('currency')!='DEMO':return False
    if doc.get('summary',{}).get('status')!='needs_review' or not doc['summary'].get('entry_sent'):return False
    trace=doc.get('trace',[])
    if not trace or any(s.get('status')!='received' for s in trace):return False
    gaming=[s for s in trace if any(x['code']<50 for x in s.get('commands',[]))]
    if len(gaming)!=1 or gaming[0]['commands']!=[{'code':1,'args':['1','25','1']}]:return False
    responses=gaming[0].get('responses',[])
    return len(responses)==1 and responses[0]['code']==1 and len(responses[0]['args'])==10 and responses[0]['args'][:2]==['1','25'] and responses[0]['args'][8:]==['1','1']

def simple_rejection_allowed(doc):
    if doc.get('game',{}).get('gid') not in SIMPLE or doc.get('authority',{}).get('practice')!=1 or doc.get('authority',{}).get('demo')!=2 or doc.get('authority',{}).get('currency')!='DEMO':return False
    if doc.get('summary',{}).get('status')!='needs_review' or not doc['summary'].get('entry_sent'):return False
    trace=doc.get('trace',[])
    if not trace or any(s.get('status')!='received' for s in trace):return False
    gaming=[s for s in trace if any(x['code']<50 for x in s.get('commands',[]))]
    return len(gaming)==1 and gaming[0]['commands']==[{'code':1,'args':['1','1','50','1']}] and gaming[0].get('responses')==[{'code':111,'args':['Game module failed']}]

def run_game(game,restart_dealt=False):
    path=FOLDER/'traces'/(game['case_slug']+'--normal.json');previous=read(path,{});rejected=False
    if previous.get('summary',{}).get('entry_sent'):
        rejected=simple_rejection_allowed(previous)
        if not rejected and not (restart_dealt and restart_allowed(previous)):return previous['summary']
    summary={'case':game['case_slug']+'--normal','id':game['id'],'slug':game['slug'],'name':game['name'],'kind':'normal','game_type':'draw_game','status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    if rejected or (restart_dealt and restart_allowed(previous)):
        archive=FOLDER/('rejected' if rejected else 'partial-deals')/(summary['case']+'--'+digest(path)[:16]+'.json');archive.parent.mkdir(exist_ok=True)
        if not archive.exists():write_json(archive,previous)
        doc['previous_attempts']=[{'file':archive.relative_to(FOLDER).as_posix(),'sha256':digest(archive),'reason':'Explicit rejection of slot-style payload; final public converter proves coins/denomination serialization.' if rejected else 'Accepted partial deal stopped by prefix parser; original session closed. Separate fresh DEMO replacement; original hand is not claimed completed.','status':'rejected' if rejected else 'accepted_partial_not_completed'}]
    def save(c):doc.update(authority=getattr(c,'authority',{}),trace=c.trace);write_json(path,doc)
    c=Playngo(game,save)
    try:
        c.bootstrap();c.connect();raw=c.configuration['settings'].removeprefix('&settings=');xml=unquote_plus(raw);initial=c.send('104 '+game['id']+' 0 %22'+raw+'%22');wallet=latest(initial,52)
        if latest(initial,104)!=['1'] or latest(initial,109) is None or not wallet or wallet[1]!='0':raise ValueError('fresh_draw_not_idle')
        source,proof=source_bundle(c,game);conf={k:c.configuration.get(k) for k in ('creditDisplay','defaultCreditDisplay','lines','defaultLimit','denom')};p=profile(game,initial,xml,source,conf)
        doc.update(profile=p,profile_proof=proof,settings_xml=xml,public_bet_configuration=conf,mode_inventory={'type':p['type'],'tested_branch':p['variant'],'other_bets':'not_exercised'})
        if rejected:
            old=next(x for s in previous['trace'] for x in s['commands'] if x['code']==1)
            if p['entry_command'].split()[1:]==old['args']:raise ValueError('rejected_parameters_not_corrected')
        summary.update(entry_sent=True,variant=p['variant'],cost_native=p['cost_native'],scale=p['scale'],balance_before_native=int(wallet[0]));save(c)
        command=p['entry_command'];all_items=[]
        for _ in range(10):
            items=c.send(command);all_items+=items;command=next_command(p,items)
            if command is None:break
        else:raise ValueError('draw_continuation_limit')
        native=settlement(p,all_items,int(wallet[0]),int(wallet[2]));doc['table_results']=[native];summary.update(native,status='completed',internal_spin_results=1,wallet_check='match');save(c)
    except Exception as exc:summary.update(status='needs_review',error=str(exc)[:300]);save(c)
    finally:c.close()
    write_json(FOLDER/'rounds.json',[read(p)['summary'] for p in (FOLDER/'traces').glob('*.json') if read(p,{}).get('summary')]);return summary

if __name__=='__main__':
    import sys
    for game in read(FOLDER/'catalog.json'):
        if game['gid'] in GAMES:print(json.dumps(run_game(game,'--restart-dealt' in sys.argv),ensure_ascii=True),flush=True)
