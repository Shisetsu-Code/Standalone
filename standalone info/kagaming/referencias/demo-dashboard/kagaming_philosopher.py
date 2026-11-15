"""Pinned 154-field PhilosopherRoulette board; offline plans and reconciliation.

The native second ball is already in md.as[0].st. It is a presentation branch
of one paid spin. Settle md.tw once, without adding the nested result's win.
"""
from decimal import Decimal
from kagaming_interactive import COMMON_SHA256, _number, _integer, _values, _digest
from kagaming_roulette import _minimum_sum, native_cost


GAME = 'PhilosopherRoulette'
SOURCE_SHA256 = '7ef0966b7f59e40458c025cca99970b43642d0f97968516273face67b5f0b4ad'
BOARD_SIZE = 154


def _limit_class(index):
    # common wg.GLa, pinned build2090 offset1600220; hJ does not override it.
    if 0 <= index <= 36: return 0
    if 49 <= index <= 81 or 130 <= index <= 153: return 1
    if 106 <= index <= 117 or index in (104, 105): return 2
    if 82 <= index <= 103: return 3
    if index == 118: return 4
    if 119 <= index <= 129: return 5
    if 40 <= index <= 42: return 6
    if 37 <= index <= 39: return 7
    if 47 <= index <= 48: return 8
    if 45 <= index <= 46: return 9
    if 43 <= index <= 44: return 10
    raise ValueError('unreviewed_philosopher_field')


def _profile(profile):
    if (profile.get('game_id') != GAME or profile.get('source_sha256') != SOURCE_SHA256
            or profile.get('common_sha256') != COMMON_SHA256
            or profile.get('board_size') != BOARD_SIZE):
        raise ValueError('unbound_philosopher_profile')
    position = profile.get('position')
    if not isinstance(position, list) or len(position) != BOARD_SIZE:
        raise ValueError('philosopher_board_dimensions')
    for value in position: _integer(value)
    index = _integer(profile.get('field_index'))
    minimum = _integer(profile.get('minimum_wager'), 1)
    if (index >= BOARD_SIZE or sum(value > 0 for value in position) != 1
            or position[index] != minimum or type(profile.get('sel')) is not int or profile['sel'] != 1):
        raise ValueError('philosopher_field_profile_mismatch')
    _integer(profile.get('cps'), 1); _integer(profile.get('atb'))
    if _number(profile.get('dn')) != Decimal('.01'):
        raise ValueError('unreviewed_philosopher_denomination')
    if _integer(profile.get('cost_native'), 1) != native_cost(position, profile['dn']):
        raise ValueError('philosopher_cost_mismatch')
    limits = profile.get('limits_native')
    if not isinstance(limits, list) or len(limits) != 13:
        raise ValueError('missing_philosopher_profile_limits')
    for value in limits: _integer(value)
    if not limits[0] <= minimum <= min(limits[1], limits[2+_limit_class(index)]):
        raise ValueError('philosopher_profile_outside_limits')
    if profile.get('kind') not in ('normal', 'variant') or not isinstance(profile.get('key'), str):
        raise ValueError('invalid_philosopher_mode')


def plans(game_id, init, source, common):
    """Return every source field admitted by native chips and table/field caps.

    Uses cash-mode cps normalization proven by pinned common I.Yha: roulette
    Uc ignores cps, and equal candidate costs leave the first chip selected.
    """
    if game_id != GAME or _digest(source) != SOURCE_SHA256 or _digest(common) != COMMON_SHA256:
        raise ValueError('unreviewed_philosopher_source')
    try:
        chips = [int(value) for value in _values(init.get('cup'), True)]
        dn = _number(init['cud'])
        md = init['sgr']['lsd']
        limits = md['sm']
        cps, atb = _integer(md['cps'], 1), _integer(md['atb'])
    except (KeyError, TypeError) as exc:
        raise ValueError('missing_philosopher_initialization') from exc
    if dn != Decimal('.01'):
        raise ValueError('unreviewed_philosopher_denomination')
    if not isinstance(limits, list) or len(limits) < 13:
        raise ValueError('missing_philosopher_table_limits')
    limits = [_integer(value) for value in limits[:13]]
    if limits[0] <= 0 or limits[1] < limits[0]:
        raise ValueError('invalid_philosopher_table_limits')
    original_cps = cps
    if cps not in chips:
        if init.get('mm') in (1, 2):
            raise ValueError('unreviewed_philosopher_cps_normalization')
        cps = chips[0]
    minimum = _minimum_sum(chips, limits[0])
    result = []
    for index in range(BOARD_SIZE):
        if minimum > min(limits[1], limits[2+_limit_class(index)]):
            continue
        position = [0]*BOARD_SIZE; position[index] = minimum
        profile = dict(game_id=GAME, kind='normal' if not result else 'variant',
                       key='normal' if not result else f'roulette-{index}',
                       label=f'Roulette field {index}', field_index=index,
                       board_size=BOARD_SIZE, minimum_wager=minimum, limits_native=limits.copy(),
                       sel=1, cps=cps, dn=float(dn), atb=atb, position=position,
                       cost_native=native_cost(position, dn),
                       cost_formula='floor(sum(pos)*dn*100+1.1920929E-7)',
                       source_sha256=SOURCE_SHA256, common_sha256=COMMON_SHA256,
                       serialization_source_sha256=COMMON_SHA256)
        if original_cps != cps:
            profile.update(initialized_cps=original_cps,
                           cps_normalization='native Yha first cash chip: roulette Uc independent of cps')
        _profile(profile); result.append(profile)
    if not result:
        raise ValueError('no_admissible_philosopher_wager')
    return result


def initial_request(profile, sid):
    _profile(profile)
    body = {key: profile[key] for key in ('sel', 'cps', 'dn', 'atb')}
    body.update(gn=GAME, sid=_integer(sid), pos=profile['position'].copy())
    return {'path': '/kaga/command/spin', 'body': body}


def assert_closed(game_id, md):
    if (game_id != GAME or not isinstance(md, dict) or md.get('v') is not True
            or md.get('fs') or md.get('rf') or md.get('bpd') or _integer(md.get('fsr')) != 0):
        raise ValueError('philosopher_round_pending_or_invalid')


def _ball(value):
    if not isinstance(value, list) or len(value) != 1 or _integer(value[0]) > 36:
        raise ValueError('invalid_philosopher_ball')


def validate_response(md, profile):
    _profile(profile); assert_closed(GAME, md)
    if type(md.get('sel')) is not int or md['sel'] != BOARD_SIZE:
        raise ValueError('philosopher_response_board_dimensions')
    position = md.get('pos')
    if not isinstance(position, list) or len(position) != BOARD_SIZE:
        raise ValueError('philosopher_missing_position_echo')
    for value in position: _integer(value)
    if position != profile['position']:
        raise ValueError('philosopher_position_echo_mismatch')
    _ball(md.get('st'))
    extra = md.get('as', [])
    if not isinstance(extra, list) or len(extra) > 1:
        raise ValueError('unreviewed_philosopher_nested_results')
    for result in extra:
        if not isinstance(result, dict):
            raise ValueError('invalid_philosopher_nested_result')
        _ball(result.get('st'))


def next_request(profile, md, sid=None):
    """All native decisions settle in one response; the second ball is local."""
    validate_response(md, profile)
    return None


def reconcile_round(profile, steps, before):
    _profile(profile); before = _integer(before)
    if not isinstance(steps, list) or len(steps) != 1:
        raise ValueError('philosopher_requires_one_paid_response')
    step = steps[0]
    if (not isinstance(step, dict) or step.get('status') != 'received'
            or step.get('http_status') != 200 or not isinstance(step.get('request'), dict)):
        raise ValueError('unconfirmed_philosopher_response')
    request, response = step['request'], step.get('response')
    expected = initial_request(profile, request.get('sid'))
    if step.get('path') != expected['path'] or request != expected['body']:
        raise ValueError('philosopher_request_mismatch')
    for key in ('sid', 'sel', 'cps', 'atb'): _integer(request.get(key))
    for value in request['pos']: _integer(value)
    if isinstance(request['dn'], bool): raise ValueError('invalid_philosopher_denomination')
    if (not isinstance(response, dict) or response.get('e') is not False
            or type(response.get('ec')) is not int or response['ec'] != 0):
        raise ValueError('unsuccessful_philosopher_response')
    md = response.get('md'); validate_response(md, profile)
    if not isinstance(md.get('tid'), str) or not md['tid']:
        raise ValueError('missing_philosopher_round_identity')
    for key in ('cps', 'dn', 'atb'):
        if key not in md or _number(md[key]) != _number(profile[key]):
            raise ValueError('philosopher_stake_echo_mismatch')
    cost, win = profile['cost_native'], _integer(md.get('tw'))
    after = before-cost+win
    if (after < 0 or _integer(response.get('sid')) != request['sid']
            or _integer(response.get('pcr')) != before-cost
            or _integer(response.get('cr')) != after or _integer(md.get('pbb')) != before
            or _integer(md.get('obb')) != after):
        raise ValueError('philosopher_wallet_or_identity_mismatch')
    return dict(game_id=GAME, key=profile['key'], kind=profile['kind'], paid_rounds=1,
                wallet_before=before, wallet_after=after, debit_native=cost, win_native=win,
                tid=md['tid'], terminal=True, decision_steps=0, source_sha256=SOURCE_SHA256,
                common_sha256=COMMON_SHA256)
