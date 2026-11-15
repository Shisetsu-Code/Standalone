"""Pure source-bound PenaltyShootout target plans and native round validation."""
import hashlib
from decimal import Decimal, InvalidOperation

SOURCE_SHA256 = '7efe5bf152715b11b6f9c88595312ff74af7d0701f13c9b68275a37322c48c5c'
COMMON_SHA256 = '6cf1bdace2d5fb0a889364ad05fa3a3a31ed2fc37aa79b36be4ee71a6e49a0f2'
GAME = 'PenaltyShootout'


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid_penalty_integer')
    return value


def _number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError('invalid_penalty_number') from error
    if isinstance(value, bool) or not number.is_finite():
        raise ValueError('invalid_penalty_number')
    return number


def _target(value):
    if _integer(value) > 9:
        raise ValueError('invalid_penalty_target')
    return value


def _profile(profile):
    position = profile.get('position')
    if not isinstance(position,list) or len(position)!=1:
        raise ValueError('invalid_penalty_position')
    target = _target(position[0])
    if (profile.get('game_id') != GAME or profile.get('source_sha256') != SOURCE_SHA256
            or profile.get('common_sha256') != COMMON_SHA256
            or profile.get('key') != ('normal' if target==0 else 'target-'+str(target))
            or profile.get('kind') != ('normal' if target==0 else 'variant')
            or type(profile.get('atb')) is not int or profile['atb']!=0):
        raise ValueError('unbound_penalty_profile')
    _integer(profile.get('sel'),1); cps=_integer(profile.get('cps'),1)
    dn=_number(profile.get('dn'));cost=100*dn*10*cps
    if dn<=0 or cost<=0 or cost!=cost.to_integral_value() or _integer(profile.get('cost_native'),1)!=cost:
        raise ValueError('penalty_cost_mismatch')
    return target


def plans(init, source, common_source):
    """Ten targets, one paid entry each; source Uc=10*cps, wallet scale=100*dn."""
    def digest(value):
        if isinstance(value,str):value=value.encode('utf8')
        if not isinstance(value,bytes):raise ValueError('invalid_penalty_source')
        return hashlib.sha256(value).hexdigest()
    if digest(source)!=SOURCE_SHA256 or digest(common_source)!=COMMON_SHA256:
        raise ValueError('unreviewed_penalty_source')
    def minimum(name, integral=False):
        values=init.get(name)
        if not isinstance(values,list) or not values:raise ValueError('missing_penalty_runtime_values')
        values=[_number(v) for v in values]
        if any(v<=0 or (integral and v!=v.to_integral_value()) for v in values):
            raise ValueError('invalid_penalty_runtime_values')
        return min(values)
    sel=int(minimum('ase',True));cps=int(minimum('cup',True));dn=minimum('dn')
    cost=100*dn*10*cps
    if cost<=0 or cost!=cost.to_integral_value():raise ValueError('nonintegral_penalty_native_cost')
    profiles=[]
    for target in range(10):
        profile=dict(game_id=GAME,sel=sel,cps=cps,dn=float(dn),atb=0,
                     cost_native=int(cost),cost_formula='native=100*dn*10*cps',
                     source_sha256=SOURCE_SHA256,common_sha256=COMMON_SHA256,
                     position=[target],key='normal' if target==0 else 'target-'+str(target),
                     kind='normal' if target==0 else 'variant')
        _profile(profile);profiles.append(profile)
    return profiles


def initial_request(profile, sid, target=None):
    default=_profile(profile);target=default if target is None else _target(target)
    body={key:profile[key] for key in ('sel','cps','dn','atb')}
    body.update(gn=GAME,sid=_integer(sid),pos=[target])
    return {'path':'/kaga/command/spin','body':body}


def _state(md):
    if not isinstance(md,dict) or md.get('v') is not True:
        raise ValueError('invalid_penalty_native_result')
    _integer(md.get('sid'));_integer(md.get('tw'))
    if not isinstance(md.get('tid'),str) or not md['tid']:
        raise ValueError('missing_penalty_round_identity')
    remaining=_integer(md.get('fsr'))
    if md.get('rf') or md.get('bpd') or md.get('fsd'):
        raise ValueError('unreviewed_penalty_obligation')
    return remaining==0


def validate_response(md, profile, request=None):
    """Validate native target/stake echoes and return whether the round is closed."""
    _profile(profile);closed=_state(md)
    position=md.get('pos')
    if not isinstance(position,list) or len(position)!=1:
        raise ValueError('missing_penalty_target_echo')
    _target(position[0])
    if request is not None and position!=request.get('pos'):
        raise ValueError('penalty_target_echo_mismatch')
    for key in ('sel','cps','dn','atb'):
        if key not in md or _number(md[key])!=_number(profile[key]):
            raise ValueError('penalty_stake_echo_mismatch')
    if 'gn' in md and md['gn']!=GAME:raise ValueError('penalty_game_echo_mismatch')
    return closed


def assert_closed(md):
    if not _state(md):raise ValueError('penalty_round_not_closed')


def next_request(profile, md, sid, target=None):
    if validate_response(md,profile):return None
    return initial_request(profile,sid,target)


def reconcile_round(profile, steps, before):
    """One debit on entry; every free spin credits only its own native tw."""
    _profile(profile);before=_integer(before)
    if not isinstance(steps,list) or not steps:raise ValueError('missing_penalty_steps')
    previous=before;prior_md=None;seen=set();win=0;tid=None
    for index,step in enumerate(steps):
        req=step.get('request',{});res=step.get('response',{});md=res.get('md')
        if (step.get('status')!='received' or step.get('http_status')!=200
                or res.get('e') is not False or type(res.get('ec')) is not int or res['ec']!=0):
            raise ValueError('unconfirmed_penalty_response')
        position=req.get('pos')
        if not isinstance(position,list) or len(position)!=1:raise ValueError('invalid_penalty_request_position')
        target=_target(position[0]);sid=_integer(req.get('sid'))
        expected=initial_request(profile,sid) if index==0 else next_request(profile,prior_md,sid,target)
        if expected is None or req!=expected['body'] or step.get('path')!=expected['path']:
            raise ValueError('penalty_request_mismatch')
        for key in ('sel','cps','atb'):_integer(req[key])
        if isinstance(req['dn'],bool):raise ValueError('invalid_penalty_denomination')
        if sid in seen or _integer(res.get('sid'))!=sid:raise ValueError('penalty_request_identity_mismatch')
        seen.add(sid);closed=validate_response(md,profile,req)
        if index==0:tid=md['tid']
        if md['tid']!=tid:raise ValueError('penalty_round_identity_changed')
        debit=profile['cost_native'] if index==0 else 0
        credit=_integer(md['tw']);balance=_integer(res.get('cr'))
        if (_integer(res.get('pcr'))!=previous-debit or balance!=previous-debit+credit
                or _integer(md.get('pbb'))!=previous or _integer(md.get('obb'))!=balance):
            raise ValueError('penalty_wallet_mismatch')
        if closed and index!=len(steps)-1:raise ValueError('penalty_steps_after_terminal')
        previous=balance;prior_md=md;win+=credit
    assert_closed(prior_md)
    return dict(balance_before_native=before,cost_native=profile['cost_native'],win_native=win,
                balance_after_native=previous,internal_steps=len(steps),paid_rounds=1,wallet_check='match')
