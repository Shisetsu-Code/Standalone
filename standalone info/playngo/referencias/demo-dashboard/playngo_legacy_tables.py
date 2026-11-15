"""Public table samples: one seat/ante/player bet; no additional stake."""
import json,re
from decimal import Decimal
from urllib.parse import unquote_plus
from playngo_rules import latest
from playngo_run import ROOT,FOLDER,read,source_bundle
from playngo_client import Playngo
from playngo_table_rules import transcript_errors
from endorphina_run import write_json

BLACKJACK={'doubleexposureblackjackmh','singledeckblackjackmh','blackjackmh','europeanblackjackmh'}
GAMES=BLACKJACK|{'casinoholdem','minibaccarat'}

def profile(game,initial,xml,source):
    gid=game['gid'];kind='blackjack' if gid in BLACKJACK else 'casinoholdem' if gid=='casinoholdem' else 'baccarat' if gid=='minibaccarat' else None
    if not kind:raise ValueError('unsupported_legacy_table')
    chips=latest(initial,54);limits=latest(initial,53)
    if not chips or not limits:raise ValueError('table_limits_missing')
    count=int(chips[0]);values=list(map(int,chips[1:count+1]));display=re.findall(r'<denom\s+Value="([\d.]+)"',xml)
    if len(display)!=count or not values or min(values)<=0:raise ValueError('table_chip_pairing_missing')
    scales={Decimal(v)/Decimal(d) for v,d in zip(values,display)}
    if len(scales)!=1:raise ValueError('table_currency_scale_ambiguous')
    scale=next(iter(scales));tag,typ={'blackjack':('Bet','2'),'casinoholdem':('Ante','4'),'baccarat':('Player','8')}[kind]
    bound=re.search('<'+tag+r'\s+Min="([\d.]+)"',xml);cost=min(values)
    if scale!=int(scale) or not bound or Decimal(bound[1])*scale!=cost or limits[0]!=typ or int(limits[1])!=cost:raise ValueError('table_minimum_not_verified')
    tokens={'blackjack':['.DEAL=1','.ACTION=2','.STAND=2','.INSURANCENO=128','.TURN=5','.OUTCOME=6','.ROUNDEND=7','e[0]=t.currentHand.toString(),e[1]=t.action.toString(),e[2]=t.seat.toString()'],
            'casinoholdem':['.DEAL=1','.PLAY=2','.OUTCOME=3','t.anteBet.toString()','t.aaBet.toString()','t.play?"1":"0"'],
            'baccarat':['.DEAL=1','.OUTCOME=3','t.playerBet.toString()','t.bankerBet.toString()','t.tieBet.toString()']}[kind]
    if not all(t in source for t in tokens):raise ValueError('table_public_schema_not_verified')
    command='1 '+str(cost)+' 0'+(' 0' if kind!='casinoholdem' else '')
    variant={'blackjack':'One seat · minimum bet · decline insurance · Stand','casinoholdem':'Minimum ante · no AA · Fold','baccarat':'Minimum player bet · no banker or tie'}[kind]
    return {'type':kind,'cost_native':cost,'scale':int(scale),'entry_command':command,'variant':variant}

def next_command(kind,items,cost):
    if any(c in (110,111) for c,a in items):raise ValueError('native_table_error')
    wallet=latest(items,52)
    if wallet and wallet[1]=='0':return None
    if kind=='blackjack':
        if latest(items,8) is not None:return '3 0 0 0'
        turn=latest(items,5)
        if not turn or len(turn)!=3:raise ValueError('blackjack_turn_missing')
        hand,mask,seat=map(int,turn)
        if seat!=0 or hand!=0:raise ValueError('blackjack_unexpected_seat_or_hand')
        if mask&128:return f'2 {hand} 128 {seat}'
        if mask&2:return f'2 {hand} 2 {seat}'
        raise ValueError('blackjack_stand_not_available')
    if kind=='casinoholdem':
        deal=latest(items,1)
        if not deal or len(deal)<9 or deal[:2]!=[str(cost),'0']:raise ValueError('casinoholdem_deal_not_verified')
        return '2 0'
    raise ValueError('table_continuation_not_proven')

def settlement(kind,items,before,bonus,cost):
    if any(c in (110,111) for c,a in items):raise ValueError('native_table_error')
    wallet=latest(items,52)
    if not wallet or wallet[1]!='0' or int(wallet[2])!=bonus:raise ValueError('table_wallet_not_closed')
    deal=latest(items,1)
    if kind in ('blackjack','baccarat') and (not deal or deal[:3]!=[str(cost),'0','0']):raise ValueError('table_accepted_bet_mismatch')
    if kind=='blackjack':
        outcomes=[a for c,a in items if c==6]
        if len(outcomes)!=1 or latest(items,7) is None or len(outcomes[0])!=4 or outcomes[0][0]!='0' or outcomes[0][3]!='0':raise ValueError('blackjack_outcome_not_verified')
        win=int(outcomes[0][2])
    elif kind=='casinoholdem':
        outcome=latest(items,3);answer=latest(items,2)
        if not outcome or len(outcome)<12 or not answer or answer[:2]!=['0','0'] or outcome[1:3]!=['0','0']:raise ValueError('casinoholdem_fold_outcome_not_verified')
        win=0
    elif kind=='baccarat':
        outcome=latest(items,3)
        if not outcome or len(outcome)!=4 or outcome[2:]!=['0','0']:raise ValueError('baccarat_player_only_outcome_not_verified')
        win=int(outcome[1])
    else:raise ValueError('unsupported_table_settlement')
    if win<0 or before-cost+win!=int(wallet[0]):raise ValueError('table_wallet_mismatch')
    return {'win_native':win,'balance_after_native':int(wallet[0])}

def verify_legacy(doc):
    errors=transcript_errors(doc['trace'])
    try:
        initial=[];gaming=[];started=False
        for step in doc['trace']:
            if step.get('status')!='received':raise ValueError('uncertain_table_request')
            if any(c['code']==1 for c in step.get('commands',[])):started=True
            (gaming if started else initial).append(step)
        initial_items=[(x['code'],x['args']) for s in initial for x in s.get('responses',[])]
        source=(ROOT/doc['profile_proof']['file']).read_text(encoding='utf8');p=profile(doc['game'],initial_items,doc['settings_xml'],source)
        if doc.get('profile')!=p:raise ValueError('table_profile_mismatch')
        before=latest(initial_items,52)
        if not before or before[1]!='0':raise ValueError('table_initial_not_idle')
        command=p['entry_command'];all_items=[]
        for step in gaming:
            parts=command.split() if command else []
            if not parts or step['commands']!=[{'code':int(parts[0]),'args':parts[1:]}]:raise ValueError('table_command_mismatch')
            items=[(x['code'],x['args']) for x in step.get('responses',[])];all_items+=items
            command=next_command(p['type'],items,p['cost_native'])
        if not gaming or command is not None:raise ValueError('table_not_complete')
        native=settlement(p['type'],all_items,int(before[0]),int(before[2]),p['cost_native'])
        expected=dict(native,cost_native=p['cost_native'],scale=p['scale'],balance_before_native=int(before[0]),internal_spin_results=1)
        if any(doc['summary'].get(k)!=v for k,v in expected.items()):raise ValueError('table_summary_mismatch')
    except Exception as exc:errors.append(str(exc))
    return errors

def run_game(game):
    path=FOLDER/'traces'/(game['case_slug']+'--normal.json');previous=read(path,{})
    if previous.get('summary',{}).get('entry_sent'):return previous['summary']
    summary={'case':game['case_slug']+'--normal','id':game['id'],'slug':game['slug'],'name':game['name'],'kind':'normal','game_type':'legacy_table','status':'running','entry_sent':False}
    doc={'game':game,'summary':summary,'trace':[]}
    def save(c):doc.update(authority=getattr(c,'authority',{}),trace=c.trace);write_json(path,doc)
    c=Playngo(game,save)
    try:
        c.bootstrap();c.connect();raw=c.configuration['settings'].removeprefix('&settings=');xml=unquote_plus(raw);initial=c.send('104 '+game['id']+' 0 %22'+raw+'%22');wallet=latest(initial,52)
        if latest(initial,104)!=['1'] or latest(initial,109) is None or not wallet or wallet[1]!='0':raise ValueError('fresh_table_not_idle')
        source,proof=source_bundle(c,game);p=profile(game,initial,xml,source);doc.update(profile=p,profile_proof=proof,settings_xml=xml,mode_inventory={'type':'table','tested_branch':p['variant'],'other_bets':'not_exercised'})
        summary.update(entry_sent=True,variant=p['variant'],cost_native=p['cost_native'],scale=p['scale'],balance_before_native=int(wallet[0]));save(c)
        command=p['entry_command'];all_items=[]
        for _ in range(10):
            items=c.send(command);all_items+=items;command=next_command(p['type'],items,p['cost_native'])
            if command is None:break
        else:raise ValueError('table_continuation_limit')
        native=settlement(p['type'],all_items,int(wallet[0]),int(wallet[2]),p['cost_native']);doc['table_results']=[native]
        summary.update(native,status='completed',internal_spin_results=1,wallet_check='match');save(c)
    except Exception as exc:summary.update(status='needs_review',error=str(exc)[:300]);save(c)
    finally:c.close()
    write_json(FOLDER/'rounds.json',[read(p)['summary'] for p in (FOLDER/'traces').glob('*.json') if read(p,{}).get('summary')]);return summary

if __name__=='__main__':
    for game in read(FOLDER/'catalog.json'):
        if game['gid'] in GAMES:print(json.dumps(run_game(game),ensure_ascii=True),flush=True)
