"""Pinned native HomeRunDerby/BonusPoker decisions; pure, offline functions.

One normal paid mode per game. HomeRun hit directions and poker hold masks
are free branches of that round. This module never sends or journals requests.
Only reconcile_round's terminal result is suitable for one round journal entry.
"""
import hashlib
from decimal import Decimal, InvalidOperation


COMMON_SHA256 = '6cf1bdace2d5fb0a889364ad05fa3a3a31ed2fc37aa79b36be4ee71a6e49a0f2'
SOURCE_SHA256 = {
    'HomeRunDerby': '2795f412cc5462370c2dbbdd99d762ab571cb6464a70ebbc95e72c88b1890087',
    'BonusPoker': '79bc5cb420603ae37f5cb9834dd24f41b14df471265160318262d954e72656b6',
}


def _number(value):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError('invalid_interactive_number') from exc
    if isinstance(value, bool) or not result.is_finite():
        raise ValueError('invalid_interactive_number')
    return result


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid_interactive_integer')
    return value


def _values(values, integral=False):
    if not isinstance(values, list) or not values:
        raise ValueError('missing_interactive_runtime_values')
    result = [_number(value) for value in values]
    if any(value <= 0 or (integral and value != value.to_integral_value()) for value in result):
        raise ValueError('invalid_interactive_runtime_values')
    return result


def _digest(source):
    if isinstance(source, str):
        source = source.encode('utf8')
    if not isinstance(source, bytes):
        raise ValueError('invalid_interactive_source')
    return hashlib.sha256(source).hexdigest()


def _profile(profile):
    game = profile.get('game_id')
    if (game not in SOURCE_SHA256 or profile.get('source_sha256') != SOURCE_SHA256[game]
            or profile.get('common_sha256') != COMMON_SHA256
            or profile.get('key') != 'normal' or profile.get('kind') != 'normal'
            or profile.get('atb') != 0 or type(profile.get('atb')) is not int):
        raise ValueError('unbound_interactive_profile')
    sel, cps = _integer(profile.get('sel'), 1), _integer(profile.get('cps'), 1)
    dn = _number(profile.get('dn'))
    if dn <= 0 or (game == 'HomeRunDerby' and sel != 1):
        raise ValueError('invalid_interactive_profile')
    cost = Decimal(10000 if game == 'HomeRunDerby' else 100) * cps * dn
    if cost != cost.to_integral_value() or cost <= 0 or profile.get('cost_native') != cost:
        raise ValueError('interactive_cost_mismatch')
    _integer(profile.get('cost_native'), 1)
    return game


def plans(game_id, init, game_source, common_source):
    """Extract the minimum paid profile from runtime ase/cup/dn lists.

    Exact source hashes bind the reviewed serializer, state machine and pricing.
    Pass source bytes to preserve line endings. Fractional wallet units fail closed.
    """
    if (game_id not in SOURCE_SHA256 or _digest(game_source) != SOURCE_SHA256[game_id]
            or _digest(common_source) != COMMON_SHA256):
        raise ValueError('unreviewed_interactive_source')
    selections = _values(init.get('ase'), True)
    if game_id == 'HomeRunDerby' and 1 not in selections:
        raise ValueError('interactive_selection_one_unavailable')
    sel = 1 if game_id == 'HomeRunDerby' else int(min(selections))
    cps, dn = int(min(_values(init.get('cup'), True))), min(_values(init.get('dn')))
    factor = 10000 if game_id == 'HomeRunDerby' else 100
    cost = factor * cps * dn
    if cost <= 0 or cost != cost.to_integral_value():
        raise ValueError('nonintegral_interactive_native_cost')
    profile = dict(game_id=game_id, sel=sel, cps=cps, dn=float(dn), atb=0,
                   key='normal', kind='normal', cost_native=int(cost),
                   cost_formula=f'native=100*dn*{100 if game_id == "HomeRunDerby" else 1}*cps',
                   source_sha256=SOURCE_SHA256[game_id], common_sha256=COMMON_SHA256)
    _profile(profile)
    return [profile]


def initial_request(profile, sid):
    """Plan the one paid deal/start; caller must use a fresh round journal."""
    game = _profile(profile)
    body = {key: profile[key] for key in ('sel', 'cps', 'atb', 'dn')}
    body.update(gn=game, sid=_integer(sid))
    if game == 'HomeRunDerby':
        body['pos'] = [0]
    return {'path': '/kaga/command/spin', 'body': body}


def _state(game, md):
    if not isinstance(md, dict):
        raise ValueError('missing_interactive_md')
    if md.get('v') is not True:
        raise ValueError('invalid_interactive_native_result')
    _integer(md.get('sid'))
    if not isinstance(md.get('tid'), str) or not md['tid']:
        raise ValueError('missing_interactive_round_identity')
    fsr = _integer(md.get('fsr'))
    _integer(md.get('tw'))
    if md.get('rf') or (game == 'BonusPoker' and md.get('fsw', 0)):
        raise ValueError('unreviewed_interactive_obligation')
    if game == 'HomeRunDerby':
        # Native HomeRun fsw is awarded count, including after settlement.
        # vod.Nba/Yra explicitly own closure through sm[0] and fsr alone.
        sm = md.get('sm')
        if not isinstance(sm, list) or not sm:
            raise ValueError('missing_home_state')
        stage = _integer(sm[0])
        if md.get('bpd') or not ((stage in (0, 2) and fsr > 0)
                                  or (stage in (1, 3) and fsr == 0)):
            raise ValueError('unreviewed_home_state')
        return stage in (1, 3)
    bpd = md.get('bpd')
    if (fsr != 0 or not isinstance(bpd, dict) or type(bpd.get('c')) is not bool
            or md.get('acb') not in (0, 2)
            or type(md.get('acb')) is not int):
        raise ValueError('unreviewed_poker_state')
    if not bpd['c'] and md['acb'] != 2:
        raise ValueError('unreviewed_poker_pending_state')
    if bpd['c']:
        draws = md.get('as')
        if (not isinstance(draws, list) or len(draws) != 1
                or not isinstance(draws[0], dict)
                or not isinstance(draws[0].get('st'), list) or len(draws[0]['st']) != 5):
            raise ValueError('missing_poker_final_cards')
    return bpd['c']


def assert_closed(game_id, md):
    if game_id not in SOURCE_SHA256 or not _state(game_id, md):
        raise ValueError('interactive_round_not_closed')


def next_request(profile, md, sid=None, direction=1, hold_mask=None, cashout=True):
    """Plan a free decision, or None after strict terminal validation.

    HomeRun defaults to one left hit then cashout; directions 1/2/3 are
    alternatives, and cashout=False permits another reviewed hit from stage2.
    Poker defaults to the native md.swm hint; explicit masks span 0..31.
    """
    game = _profile(profile)
    if _state(game, md):
        return None
    if game == 'HomeRunDerby':
        if type(direction) is not int or direction not in (1, 2, 3) or type(cashout) is not bool:
            raise ValueError('invalid_home_decision')
        result = initial_request(profile, sid)
        result['body']['pos'] = [4 if md['sm'][0] == 2 and cashout else direction]
        return result
    mask = md.get('swm', 0) if hold_mask is None else hold_mask
    _integer(mask)
    if mask > 31:
        raise ValueError('invalid_poker_hold_mask')
    return {'path': '/kaga/command/bonusPick',
            'body': {'gn': game, 'p': mask, 'sid': md['sid']}}


def reconcile_round(profile, steps, wallet_before):
    """Validate complete native journals and return exactly one terminal entry.

    Each step is DemoClient's {path,request,response} shape. Until settlement,
    reviewed pending states must have tw=0 and no further wallet debit. Changed
    tid, replayed spin sid, extra/missing request fields and incomplete rounds
    fail closed. Native md.sid may change; bonusPick uses its previous value.
    """
    game = _profile(profile)
    wallet_before = _integer(wallet_before)
    if not isinstance(steps, list) or not steps:
        raise ValueError('missing_interactive_steps')
    previous, wallet, tid, seen_spin = None, wallet_before, None, set()
    for index, step in enumerate(steps):
        if (not isinstance(step, dict) or not isinstance(step.get('request'), dict)
                or step.get('status') != 'received' or step.get('http_status') != 200):
            raise ValueError('missing_interactive_request')
        request, response = step['request'], step.get('response')
        if index == 0:
            expected = initial_request(profile, request.get('sid'))
        elif game == 'HomeRunDerby':
            pos = request.get('pos')
            if (not isinstance(pos, list) or len(pos) != 1 or type(pos[0]) is not int
                    or pos[0] not in (1, 2, 3, 4)):
                raise ValueError('invalid_home_position')
            expected = next_request(profile, previous, sid=request.get('sid'),
                                    direction=pos[0] if pos[0] != 4 else 1, cashout=pos[0] == 4)
        else:
            expected = next_request(profile, previous, hold_mask=request.get('p'))
        if expected is None or step.get('path') != expected['path'] or request != expected['body']:
            raise ValueError('interactive_request_mismatch')
        # Equality alone equates True with 1; every native field has an exact type.
        for key in ('sel', 'sid', 'cps', 'atb', 'p'):
            if key in request: _integer(request[key])
        if 'dn' in request and isinstance(request['dn'], bool):
            raise ValueError('invalid_interactive_denomination')
        if step['path'].endswith('/spin'):
            if request['sid'] in seen_spin:
                raise ValueError('replayed_interactive_spin')
            seen_spin.add(request['sid'])
        if (not isinstance(response, dict) or response.get('e') is not False
                or type(response.get('ec')) is not int or response['ec'] != 0):
            raise ValueError('unsuccessful_interactive_response')
        md = response.get('md')
        if game == 'BonusPoker' and index > 0:
            if _integer(response.get('p')) != request['p']:
                raise ValueError('poker_choice_echo_mismatch')
        terminal = _state(game, md)
        if index == 0:
            tid = md['tid']
            if terminal or (game == 'HomeRunDerby' and md['sm'][0] != 0):
                raise ValueError('unexpected_interactive_start_state')
        elif game == 'BonusPoker' and not terminal:
            raise ValueError('unreviewed_additional_poker_draw')
        elif game == 'HomeRunDerby':
            if (md['sm'][0] == 0
                    or (request['pos'] == [4] and md['sm'][0] != 3)):
                raise ValueError('unreviewed_home_transition')
        if md['tid'] != tid:
            raise ValueError('interactive_round_identity_changed')
        win = md['tw'] if terminal else 0
        if not terminal and md['tw'] != 0:
            raise ValueError('unreviewed_pending_interactive_credit')
        debit = profile['cost_native'] if index == 0 else 0
        if step['path'].endswith('/spin'):
            if (_integer(response.get('sid')) != request['sid']
                    or _integer(response.get('pcr')) != wallet-debit
                    or _integer(md.get('pbb')) != wallet
                    or _integer(md.get('obb')) != _integer(response.get('cr'))):
                raise ValueError('interactive_spin_echo_mismatch')
            for key in ('sel', 'cps', 'atb', 'dn'):
                if key not in md or _number(md[key]) != _number(profile[key]):
                    raise ValueError('interactive_stake_echo_mismatch')
        else:
            # Fd does not parse root sid/pcr. Round pbb/obb may retain deal values.
            for key in ('sel', 'cps', 'atb', 'dn'):
                if key in md and _number(md[key]) != _number(profile[key]):
                    raise ValueError('interactive_stake_echo_mismatch')
        wallet = wallet - debit + win
        if wallet < 0 or _integer(response.get('cr')) != wallet:
            raise ValueError('interactive_wallet_mismatch')
        if terminal and index != len(steps)-1:
            raise ValueError('interactive_steps_after_terminal')
        previous = md
    assert_closed(game, previous)
    return dict(game_id=game, key=profile['key'], kind=profile['kind'], paid_rounds=1,
                debit_native=profile['cost_native'], win_native=previous['tw'],
                wallet_before=wallet_before, wallet_after=wallet, tid=tid,
                terminal=True, decision_steps=len(steps)-1,
                source_sha256=profile['source_sha256'], common_sha256=COMMON_SHA256)
