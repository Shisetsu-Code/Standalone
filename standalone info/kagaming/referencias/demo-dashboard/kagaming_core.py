"""KA native demo evidence. Unknown choices never become invented actions."""
import hashlib,re
from decimal import Decimal
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

SECRET={'un','u','ak','to','t','si','sessionid','session','token','authorization','cookie','cookies','password','accesskey','ctx'}

def sanitize(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.sub('[^a-z0-9]','',k.lower()) in SECRET else value[k] if k=='tid' and str(value[k]).startswith('round-') else 'round-'+hashlib.sha256(str(v).encode()).hexdigest()[:20] if k=='tid' else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str) and value.startswith(('https://','http://')):
        u=urlsplit(value);return urlunsplit((u.scheme,u.netloc,u.path,urlencode([(k,'[REDACTED]' if k.lower() in SECRET else v) for k,v in parse_qsl(u.query,keep_blank_values=True)]),''))
    return value

def integer(value):
    d=Decimal(str(value))
    if isinstance(value,bool) or not d.is_finite() or d!=int(d):raise ValueError('invalid_native_integer')
    return int(d)

def catalog_from_response(response):
    if response.get('status')!='ok' or response.get('statusCode')!=0 or response.get('gameLaunchURL')!='https://gamesdemo.kaga88.com' or response['numGames']!=len(response['games']):raise ValueError('incomplete_or_unverified_demo_catalog')
    games=[];seen=set()
    for i,g in enumerate(response['games'],1):
        gid=g['gameId']
        if not re.fullmatch('[A-Za-z0-9_]+',gid) or gid in seen:raise ValueError('ambiguous_catalog_game')
        seen.add(gid);games.append(dict(g,ordinal=i,id=gid,name=g['gameName'],provider='kagaming'))
    return games

def needs_continuation(md,game=None):
    if game=='PhilosopherRoulette':
        from kagaming_philosopher import assert_closed
        assert_closed(game,md);return False
    if game=='AmericanRoulette':
        from kagaming_american import assert_closed
        assert_closed(md);return False
    if game=='ChickenQuest':
        from kagaming_chicken import _state
        return not _state(game,md)
    if game=='PenaltyShootout':
        from kagaming_penalty import _state
        return not _state(md)
    if game in ('HomeRunDerby','BonusPoker'):
        from kagaming_interactive import _state
        return not _state(game,md)
    from kagaming_bonus_pick import is_supported
    if is_supported(game) and md.get('bpd'):
        from pathlib import Path
        from kagaming_bonus_pick import decision
        root=Path(__file__).parent/'kagaming/reference'
        return decision(game,md,(root/(game.lower()+'.js')).read_bytes(),(root/'game.min.2090.js').read_bytes())['action']!='closed'
    if game=='FortuneSkyLanterns':
        from kagaming_lanterns import assert_closed
        assert_closed(md);return False
    if game=='FrenchRoulette':
        from kagaming_roulette import assert_closed
        assert_closed(md);return False
    if md.get('bpd'):raise ValueError('native_bonus_choice_requires_review')
    if md.get('rf',0):raise ValueError('native_respin_state_requires_review')
    remaining=integer(md.get('fsr',0))
    if remaining<0:raise ValueError('invalid_free_spin_count')
    if md.get('fsd') and remaining:raise ValueError('bundled_free_spins_require_review')
    if game=='Shopping':
        state=md.get('sm',[])
        if not state or state[0] not in (-1,0,1,2,3):raise ValueError('shopping_state_requires_review')
        return not(state[0] in (-1,3) and remaining==0)
    return remaining>0

def reconcile(before,cost,steps,profile=None):
    game=steps[0]['request'].get('gn') if steps else None
    if game=='PenaltyShootout':
        from kagaming_penalty import reconcile_round
        if not profile or profile.get('cost_native')!=cost:raise ValueError('missing_penalty_profile')
        return reconcile_round(profile,steps,before)
    if game in ('HomeRunDerby','BonusPoker','ChickenQuest','PhilosopherRoulette'):
        if game=='PhilosopherRoulette':
            from kagaming_philosopher import reconcile_round
        elif game=='ChickenQuest':
            from kagaming_chicken import reconcile_round
        else:
            from kagaming_interactive import reconcile_round
        if not profile or profile.get('cost_native')!=cost:raise ValueError('missing_interactive_cost_profile')
        result=reconcile_round(profile,steps,before)
        return {'balance_before_native':result['wallet_before'],'cost_native':result['debit_native'],'win_native':result['win_native'],'balance_after_native':result['wallet_after'],'internal_steps':len(steps),'wallet_check':'match','paid_rounds':result['paid_rounds']}
    from kagaming_bonus_pick import is_supported
    if is_supported(game) and any(s.get('response',{}).get('md',{}).get('bpd') for s in steps):
        from pathlib import Path
        from kagaming_bonus_pick import reconcile_round
        root=Path(__file__).parent/'kagaming/reference'
        return reconcile_round(before,cost,steps,(root/(game.lower()+'.js')).read_bytes(),(root/'game.min.2090.js').read_bytes())
    before=integer(before);cost=integer(cost)
    if cost<=0 or not steps:raise ValueError('no_paid_round')
    previous=before;win=0;ids=set();first=steps[0]['request'];first_tid=steps[0]['response'].get('md',{}).get('tid')
    for i,step in enumerate(steps):
        req=step['request'];res=step.get('response',{});md=res.get('md',{})
        if step.get('status')!='received' or step.get('http_status')!=200 or res.get('e') is not False or res.get('ec')!=0 or md.get('v') is not True:raise ValueError('unconfirmed_native_response')
        if req.get('sid')!=res.get('sid') or req.get('sid') in ids:raise ValueError('native_request_identity_mismatch')
        ids.add(req['sid'])
        if i:
            if not needs_continuation(steps[i-1]['response']['md'],first.get('gn')):raise ValueError('additional_paid_entry_after_closed_round')
            continuation_atb=0 if first.get('gn')=='HotCoinBF' and 1<=first.get('atb',0)<=9 else first.get('atb')
            allowed_position=req.get('pos') in ([0],[1],[2]) if first.get('gn')=='Shopping' else not req.get('pos')
            if first.get('gn')=='AlienDairy':allowed_position=req.get('pos') in ([0],[1],[2],[3],[4],[5])
            if not allowed_position or req.get('atb')!=continuation_atb or any(req.get(k)!=first.get(k) for k in ('gn','sel','cps','dn')) or md.get('tid')!=first_tid:raise ValueError('unexpected_paid_or_changed_continuation')
        pcr=integer(res['pcr']);balance=integer(res['cr']);credit=integer(md['tw'])
        if pcr!=previous-(cost if i==0 else 0) or balance!=pcr+credit or credit<0:raise ValueError('native_wallet_mismatch')
        if integer(md['pbb'])!=previous or integer(md['obb'])!=balance:raise ValueError('native_wallet_echo_mismatch')
        echo_fields=('sel','cps','dn','atb')
        if first.get('gn') in ('FrenchRoulette','AmericanRoulette'):
            board=158 if first['gn']=='AmericanRoulette' else 157
            position=req.get('pos')
            if not isinstance(position,list) or len(position)!=board or any(integer(x)<0 for x in position) or req.get('sel')!=sum(x>0 for x in position) or md.get('sel')!=board:raise ValueError('roulette_board_or_selection_mismatch')
            echo_fields=('cps','dn','atb')
        if any(Decimal(str(req[k]))!=Decimal(str(md[k])) for k in echo_fields):raise ValueError('native_parameter_echo_mismatch')
        win+=credit;previous=balance
    if needs_continuation(steps[-1]['response']['md'],first.get('gn')):raise ValueError('native_round_not_closed')
    if before-cost+win!=previous:raise ValueError('round_wallet_mismatch')
    return {'balance_before_native':before,'cost_native':cost,'win_native':win,'balance_after_native':previous,'internal_steps':len(steps),'wallet_check':'match'}

def hash31(value):
    raw=value.encode('utf-16-le',errors='surrogatepass');h=0
    for i in range(0,len(raw),2):h=(31*h+int.from_bytes(raw[i:i+2],'little'))&0xffffffff
    return h if h<0x80000000 else h-0x100000000

def sign_context(body_text,context,timestamp_ms):
    import hashlib
    context=dict(context);d=str(integer(timestamp_ms));v=context['idv'];b=context['dv']
    g='SzXS@78TWls@x9&$5212Qw*oOZP@!tQybp5msFRpt1b@kaqN@3ms2932733tSyst'
    e=str(hash31(body_text+'2090'+v+d));f=str(hash31(d+v+b))
    source=d+'1.0.268 (2090)'+e+g+f+body_text+'2090' if int(e)%2==0 else g+body_text+f+b+e+'2090'+d
    context['ida']=hashlib.sha256(source.encode('utf8')).hexdigest()+d
    return context

def captured_rounds(fixture):
    start=next(s['response'] for s in fixture['steps'] if s['path'].endswith('/startGame'));before=integer(start['bl']);rounds=[];current=[];cost=None
    for step in fixture['steps']:
        if not step['path'].endswith('/spin'):continue
        if not current:cost=before-integer(step['response']['pcr'])
        current.append(step)
        if not needs_continuation(step['response']['md']):
            result=reconcile(before,cost,current);rounds.append(dict(result,kind='buy' if current[0]['request'].get('pos') else 'ante' if current[0]['request'].get('atb') else 'normal',steps=current));before=result['balance_after_native'];current=[]
    if current:raise ValueError('captured_round_incomplete')
    return rounds
