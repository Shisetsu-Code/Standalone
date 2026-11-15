"""Source-bound ChickenQuest start/hop/cashout; no network or journal writes.

Source ywd uses sel1 despite the unrelated UI gd43 constant. Its sole paid
mode starts pos0; hop1 and cashout3 are free decisions. Guard accepting pos2
in kc is not a UI choice proof, so this planner never sends it.
"""
from decimal import Decimal
from kagaming_interactive import COMMON_SHA256, _number, _integer, _values, _digest


SOURCE_SHA256 = '584d449e76337cae9689f146256a85ce143a9af53c9059a264b640f9fe55dbd6'
GAME = 'ChickenQuest'


def _profile(profile):
    if (profile.get('game_id') != GAME or profile.get('source_sha256') != SOURCE_SHA256
            or profile.get('common_sha256') != COMMON_SHA256
            or profile.get('key') != 'normal' or profile.get('kind') != 'normal'
            or type(profile.get('sel')) is not int or profile['sel'] != 1
            or type(profile.get('atb')) is not int or profile['atb'] != 0):
        raise ValueError('unbound_chicken_profile')
    cps, dn = _integer(profile.get('cps'), 1), _number(profile.get('dn'))
    cost = Decimal(10000)*cps*dn
    if (dn <= 0 or cost != cost.to_integral_value() or cost <= 0
            or _integer(profile.get('cost_native'), 1) != cost):
        raise ValueError('chicken_cost_mismatch')


def plans(game_id, init, source, common):
    if game_id != GAME or _digest(source) != SOURCE_SHA256 or _digest(common) != COMMON_SHA256:
        raise ValueError('unreviewed_chicken_source')
    if 1 not in _values(init.get('ase'), True):
        raise ValueError('chicken_selection_one_unavailable')
    cps, dn = int(min(_values(init.get('cup'), True))), min(_values(init.get('dn')))
    cost = 10000*cps*dn
    if cost <= 0 or cost != cost.to_integral_value():
        raise ValueError('nonintegral_chicken_native_cost')
    result = dict(game_id=GAME, key='normal', kind='normal', sel=1, cps=cps,
                  dn=float(dn), atb=0, cost_native=int(cost),
                  cost_formula='native=100*dn*100*cps', source_sha256=SOURCE_SHA256,
                  common_sha256=COMMON_SHA256)
    _profile(result)
    return [result]


def initial_request(profile, sid):
    _profile(profile)
    body = {key: profile[key] for key in ('sel', 'cps', 'dn', 'atb')}
    body.update(gn=GAME, sid=_integer(sid), pos=[0])
    return {'path': '/kaga/command/spin', 'body': body}


def _state(game, md):
    if game != GAME or not isinstance(md, dict) or md.get('v') is not True:
        raise ValueError('invalid_chicken_native_result')
    _integer(md.get('sid')); _integer(md.get('tw'))
    if not isinstance(md.get('tid'), str) or not md['tid']:
        raise ValueError('missing_chicken_round_identity')
    if md.get('rf') or md.get('bpd'):
        raise ValueError('unreviewed_chicken_obligation')
    # fsw is an awarded counter, not an outstanding decision. Source Nba/Yra
    # closes explicitly on stage -1/1/3 and fsr0; fs flag alone does not decide.
    remaining = _integer(md.get('fsr'))
    sm = md.get('sm')
    if not isinstance(sm, list) or not sm:
        raise ValueError('missing_chicken_stage')
    stage = _integer(sm[0], -1)
    if stage in (-1, 1, 3) and remaining == 0:
        return True
    if stage in (0, 2) and remaining > 0:
        return False
    raise ValueError('unreviewed_chicken_state')


def assert_closed(game, md):
    if not _state(game, md):
        raise ValueError('chicken_round_not_closed')


def next_request(profile, md, sid=None, cashout=True):
    _profile(profile)
    if _state(GAME, md):
        return None
    if type(cashout) is not bool:
        raise ValueError('invalid_chicken_choice')
    result = initial_request(profile, sid)
    result['body']['pos'] = [3 if md['sm'][0] == 2 and cashout else 1]
    return result


def reconcile_round(profile, steps, before):
    """Validate a complete DemoClient journal; return one paid-round summary.

    Pending tw0 is deliberately fail-closed until native packets prove any
    alternative credit schedule. Continuations require previous positive fsr.
    """
    _profile(profile)
    wallet = _integer(before)
    if not isinstance(steps, list) or not steps:
        raise ValueError('missing_chicken_steps')
    previous, tid, seen = None, None, set()
    for index, step in enumerate(steps):
        if (not isinstance(step, dict) or step.get('status') != 'received'
                or step.get('http_status') != 200 or not isinstance(step.get('request'), dict)):
            raise ValueError('unconfirmed_chicken_step')
        request, response = step['request'], step.get('response')
        for key in ('sel', 'cps', 'atb', 'sid'): _integer(request.get(key))
        pos = request.get('pos')
        if (not isinstance(pos, list) or len(pos) != 1 or type(pos[0]) is not int
                or pos[0] not in (0, 1, 3)):
            raise ValueError('unreviewed_chicken_position')
        expected = (initial_request(profile, request['sid']) if index == 0 else
                    next_request(profile, previous, request['sid'], cashout=pos[0] == 3))
        if (expected is None or step.get('path') != expected['path'] or request != expected['body']
                or request['sid'] in seen or isinstance(request.get('dn'), bool)):
            raise ValueError('chicken_request_mismatch')
        seen.add(request['sid'])
        if (not isinstance(response, dict) or response.get('e') is not False
                or type(response.get('ec')) is not int or response['ec'] != 0):
            raise ValueError('unsuccessful_chicken_response')
        md = response.get('md'); terminal = _state(GAME, md)
        if index == 0:
            tid = md['tid']
            if terminal or md['sm'][0] != 0:
                raise ValueError('unexpected_chicken_start_state')
        elif md['sm'][0] == 0 or (pos == [3] and md['sm'][0] != 3):
            raise ValueError('unreviewed_chicken_transition')
        if md['tid'] != tid:
            raise ValueError('chicken_round_identity_changed')
        debit = profile['cost_native'] if index == 0 else 0
        if (not terminal and md['tw'] != 0):
            raise ValueError('unreviewed_pending_chicken_credit')
        win = md['tw'] if terminal else 0
        if (_integer(response.get('sid')) != request['sid']
                or _integer(response.get('pcr')) != wallet-debit
                or _integer(md.get('pbb')) != wallet
                or _integer(md.get('obb')) != _integer(response.get('cr'))):
            raise ValueError('chicken_wallet_echo_mismatch')
        for key in ('sel', 'cps', 'dn', 'atb'):
            if key not in md or _number(md[key]) != _number(profile[key]):
                raise ValueError('chicken_stake_echo_mismatch')
        wallet = wallet-debit+win
        if wallet < 0 or _integer(response.get('cr')) != wallet:
            raise ValueError('chicken_wallet_mismatch')
        if terminal and index != len(steps)-1:
            raise ValueError('chicken_step_after_terminal')
        previous = md
    assert_closed(GAME, previous)
    return dict(game_id=GAME, key='normal', kind='normal', paid_rounds=1,
                wallet_before=before, wallet_after=wallet, debit_native=profile['cost_native'],
                win_native=previous['tw'], tid=tid, terminal=True, decision_steps=len(steps)-1,
                source_sha256=SOURCE_SHA256, common_sha256=COMMON_SHA256)
