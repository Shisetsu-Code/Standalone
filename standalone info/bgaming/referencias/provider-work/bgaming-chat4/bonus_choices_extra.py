"""Pinned source contracts for three bonus choices; no automatic gameplay or networking.

metadata/prepare/check_event are pure. continue_once is an opt-in, single request
hook for the parent runner after restore(), owned FUN and pacing checks. It never
opens a round, retries, settles a different state, renews FUN, or writes reports.
Synthetic test outcomes are not provider observations or coverage claims.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re

PINS = {
    'DigDigDigger': 'fb184c286f5cf73a3f1bcaedc1b22dbbbb8aa1050dd08e649a5cf7971f04fa97',
    'WildMoonThieves': '9bec7ce8437c85e5d4a234f865065574c1165b7556b96ef0b0bd5928790f0f0e',
    'LuckyLadyClover': 'bbfca3c458135f414aaf3c441f015ab330a5d410f2d99b1654ee270efce899ed',
}
CARDS = ('s', 'c', 'd', 'h', 'black', 'red')


def metadata(gid, source):
    """Reject different clients/versions rather than borrowing another game's schema."""
    digest = hashlib.sha256(source.encode('utf8')).hexdigest()
    if gid not in PINS or digest != PINS[gid]:
        raise ValueError('Reviewed game-specific source digest required')
    if gid == 'DigDigDigger':
        choices = list(dict.fromkeys(re.findall(r'onClick:"currentScene\.playGamble`([a-z]+)"', source)))
        needles = [
            'command:zt.isApi2?"gamble":"check_card",options:{bet:t,additionalInfo:e}',
            'command:zt.isApi2?"close":"finish"',
            'qt.gamble(t).then(',
            'o.A.data.isGambleWin=e.gamble&&e.gamble.win',
            'o.A.data.isGambleWin?(',
            't.gameTotalWin=t.balance.game',
            'o.A.data.gambleSuitPossibleWin=4*t,o.A.data.gambleColorPossibleWin=2*t',
        ]
        if set(choices) != set(CARDS):
            raise ValueError('Six literal card controls required')
        family, command, close = 'api2-pending-game-balance', 'gamble', 'close'
    elif gid == 'WildMoonThieves':
        choices = sorted(set(map(int, re.findall(r'clickDoor`(\d+)', source))))
        if choices != list(range(16)):
            raise ValueError('Sixteen literal door controls required')
        needles = [
            'var e={command:"play_preselection_game",options:t};qt.sendCommand(e)',
            'this.sendCommand({index:t})', 'this.sendCommand({mode:"auto"})',
            'this.doorsNew=i.new_doors,this.doorsHistory=i.doors,this.isFinishGame=!!i.finished',
        ]
        family, command, close = 'api2-door-preselection', 'play_preselection_game', None
    else:
        choices = list(CARDS)
        needles = [
            'function RS({request:e,ButtonsManager:t})',
            'function rP(){const e=AS({Gamble:RS});e.load(["slot/LuckyLadyClover/gamble.json"',
            'My.games.LuckyLadyClover={init:rP}',
            'case"spades":case"clubs":case"diamonds":case"hearts":n=n.toString()[0]',
            'case"black":n="black";break;case"red":n="red"',
            'let r={command:"check_card",options:{bet:n}}',
            'this.win=this.slot_result.bets.required_for_bonus_game',
            '"win"==e.game.bonus_game.result&&e.result&&(i.win=e.result.total)',
            'i.totalWin=e.balance-i.slot_result.balance',
            'innerHTML=4*e/this.game_data.options.currency.subunits',
            'innerHTML=2*e/this.game_data.options.currency.subunits',
            'U("finish")?(je(),j("finish"),J_.request({command:"finish"}',
            'let r=n.result&&n.result.total?n.result.total:0',
        ]
        family, command, close = 'classic-rs-native-credited-balance', 'check_card', 'finish'
    evidence = []
    for needle in needles:
        offset = source.find(needle)
        if offset < 0:
            raise ValueError('Reviewed source contract missing')
        evidence.append({'offset': offset, 'excerpt': needle})
    return dict(game_id=gid, source_verified=True, source_sha256=digest,
                family=family, choices=choices, command=command,
                collect_command=close, evidence=evidence,
                wire_note='Choice is semantic; never scale it as money. Omit undefined additionalInfo.')


def _meta(meta):
    gid = meta.get('game_id')
    if not meta.get('source_verified') or meta.get('source_sha256') != PINS.get(gid) or gid not in PINS:
        raise ValueError('Pinned source metadata required')
    expected = list(range(16)) if gid == 'WildMoonThieves' else list(CARDS)
    if set(meta.get('choices', [])) != set(expected):
        raise ValueError('Source choice set differs')
    return gid


def _native(value):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative native integer required')
    return value


def _balance(response):
    b = response.get('balance', {})
    return _native(b.get('wallet')), _native(b.get('game'))


def _door_history(response):
    data = response.get('features', {}).get('preselection_game', {})
    doors = data.get('doors', [])
    if not isinstance(doors, list):
        raise ValueError('Door history malformed')
    indices = []
    for entry in doors:
        index = entry.get('index')
        if type(index) is not int or not 0 <= index < 16 or index in indices:
            raise ValueError('Door history index malformed/duplicate')
        _native(entry.get('wilds'))
        indices.append(index)
    return data, doors, indices


def prepare(before, meta, choice):
    """Build a single advertised continuation; never spin/init/purchase a trigger."""
    gid = _meta(meta)
    if gid == 'LuckyLadyClover':
        available = before.get('available_commands', [])
        state = before.get('game', {}).get('state')
        command = 'finish' if choice == 'collect' else 'check_card'
        if state != 'check_card' or command not in available:
            raise ValueError('Classic winning round continuation not advertised')
        if choice != 'collect' and (type(choice) is not str or choice not in CARDS):
            raise ValueError('Unknown semantic card choice')
    else:
        flow = before.get('flow', {})
        available, state = flow.get('available_actions', []), flow.get('state')
        _balance(before)
        if gid == 'DigDigDigger':
            command = 'close' if choice == 'collect' else 'gamble'
            if state != 'gamble' or command not in available or before['balance']['game'] <= 0:
                raise ValueError('Pending positive gamble round not advertised')
            if choice != 'collect' and (type(choice) is not str or choice not in CARDS):
                raise ValueError('Unknown semantic card choice')
        else:
            command = 'play_preselection_game'
            if state != 'preselection_game' or command not in available:
                raise ValueError('Pending door continuation not advertised')
            data, doors, opened = _door_history(before)
            if data.get('finished') or type(choice) is not int or choice not in range(16) or choice in opened:
                raise ValueError('Door outside source range, already open, or finished')
            return {'command': command, 'options': {'index': choice}}
    return {'command': command} if choice == 'collect' else {'command': command, 'options': {'bet': choice}}


def check_event(before, event, meta):
    """Assert native conservation and source semantics without rewriting a response."""
    gid = _meta(meta)
    request, after = event['request'], event['response']
    command = request.get('command')
    choice = 'collect' if command in ('close', 'finish') else request.get('options', {}).get('index' if gid == 'WildMoonThieves' else 'bet')
    prepared = prepare(before, meta, choice)
    actual = {k: v for k, v in request.items() if k != 'extra_data'}
    if event.get('status') != 200 or actual != prepared or after.get('errors'):
        raise ValueError('Received request/status differs from prepared continuation')
    if gid == 'LuckyLadyClover':
        old, new = _native(before.get('balance')), _native(after.get('balance'))
        state = after.get('game', {}).get('state')
        if command == 'finish':
            if state != 'closed' or new != old:
                raise ValueError('Finish must close without crediting already-paid prize again')
            return dict(kind='classic_finish_native_balance', expected=old, actual=new, effective_balance_native=new, ok=True)
        stake = _native(before.get('bets', {}).get('required_for_bonus_game'))
        game = after.get('game', {}).get('bonus_game', {})
        result = after.get('result')
        outcome = game.get('result')
        if not stake or outcome not in ('win', 'lose') or not isinstance(game.get('card'), str) or not game['card']:
            raise ValueError('Classic native stake/card result missing')
        payout = 0 if result is None and outcome == 'lose' else _native((result or {}).get('total'))
        expected_payout = stake * (2 if choice in ('black', 'red') else 4) if outcome == 'win' else 0
        if payout != expected_payout or new != old - stake + payout or state not in ('check_card', 'closed'):
            raise ValueError('Classic native gamble balance/outcome mismatch')
        if outcome == 'lose' and state != 'closed':
            raise ValueError('Losing classic gamble must close')
        if 'bet' in game and game['bet'] != choice:
            raise ValueError('Classic response choice mismatch')
        if 'bonus_game' in after.get('bets', {}) and after['bets']['bonus_game'] != stake:
            raise ValueError('Classic response stake mismatch')
        if result and 'bonus_game' in result and result['bonus_game'] != payout:
            raise ValueError('Classic response payout mismatch')
        if state == 'check_card' and 'required_for_bonus_game' in after.get('bets', {}) and after['bets']['required_for_bonus_game'] != payout:
            raise ValueError('Next classic gamble stake mismatch')
        return dict(kind='classic_rs_gamble_native_balance', choice=choice, stake_native=stake, payout_native=payout, expected=new, actual=new, effective_balance_native=new, ok=True)
    old_wallet, old_game = _balance(before)
    wallet, game_balance = _balance(after)
    flow = after.get('flow', {})
    previous = before['flow']
    if flow.get('round_id') != previous.get('round_id') or not flow.get('round_id') or flow.get('command') != command:
        raise ValueError('Continuation changed parent round or command')
    if not (gid == 'DigDigDigger' and command == 'close') and (not flow.get('last_action_id') or flow['last_action_id'] == previous.get('last_action_id')):
        raise ValueError('Continuation did not produce a new action')
    if gid == 'DigDigDigger':
        if command == 'close':
            expected = old_wallet + old_game
            if flow.get('state') != 'closed' or wallet + game_balance != expected or game_balance not in (0, old_game):
                raise ValueError('Close must conserve pending prize exactly once')
            return dict(kind='api2_collect_native_balance', expected=expected, actual=wallet + game_balance, effective_balance_native=expected, ok=True)
        win = after.get('gamble', {}).get('win')
        if type(win) is not bool and not (type(win) is int and win >= 0):
            raise ValueError('Native gamble.win must be boolean or nonnegative integer truthiness marker')
        payout = old_game * (2 if choice in ('black', 'red') else 4) if bool(win) else 0
        if 'bet' in after.get('gamble', {}) and after['gamble']['bet'] != old_game:
            raise ValueError('Native gamble.bet differs from reserved game stake')
        if wallet != old_wallet or game_balance != payout or flow.get('state') not in ('gamble', 'closed') or (not win and flow.get('state') != 'closed'):
            raise ValueError('API2 pending native gamble balance/outcome mismatch')
        return dict(kind='api2_gamble_native_balance', choice=choice, stake_native=old_game, payout_native=payout,
                    wallet_native=wallet, source_win_value=win, effective_balance_native=wallet + game_balance, ok=True)
    data, doors, indices = _door_history(after)
    prior, prior_doors, prior_indices = _door_history(before)
    new_doors = data.get('new_doors')
    if type(data.get('finished')) is not bool or type(data.get('doors_auto_open_flag')) is not bool or not isinstance(new_doors, list):
        raise ValueError('Source door result fields missing')
    if doors[:len(prior_doors)] != prior_doors or new_doors != doors[len(prior_doors):] or not any(d.get('index') == choice for d in new_doors):
        raise ValueError('Door result does not confirm new selected door/history')
    if wallet != old_wallet or game_balance != old_game:
        raise ValueError('Door selection unexpectedly changed native money')
    if (not data['finished'] and flow.get('state') != 'preselection_game') or (data['finished'] and flow.get('state') not in ('freespins', 'respin')):
        raise ValueError('Door finish flag does not match bonus transition')
    return dict(kind='manual_door_native_balance', choice=choice, opened_indices=indices,
                preselection_finished=data['finished'], expected=old_wallet + old_game,
                actual=wallet + game_balance, effective_balance_native=wallet + game_balance, ok=True)


def continue_once(report, credentials, meta, choice, claim_path, call, clean):
    """Opt-in hook: atomic claim before one d.call; never replay uncertain dispatch.

    Parent owns its runner lock, stop gate, >=60s game-launch spacing, restore(),
    optional source-verified readback adoption, and public/private checkpoint saves.
    claim_path must be unique per owned context + parent round + logical action.
    Keep every claim after dispatch, including on transport/validation failure.
    No new sessions, init, paid trigger, automatic searches, or retries occur here.
    """
    gid = _meta(meta)
    events = report.get('events', [])
    if not events or not credentials.get('fresh_demo') or credentials.get('game_id') != gid or report.get('game', {}).get('game_id') != gid or credentials.get('operation', {}).get('status') != 'received':
        raise ValueError('Received fresh owned QA context required')
    before = credentials.get('last_response')
    if clean(copy.deepcopy(before)) != events[-1]['response']:
        raise ValueError('Private/public received checkpoint mismatch')
    currency = events[0]['response'].get('options', {}).get('currency', {})
    if currency.get('code') != 'FUN' or currency.get('subunits') != 100:
        raise ValueError('Native FUN checkpoint required')
    request = prepare(before, meta, choice)
    checkpoint = hashlib.sha256(json.dumps(events[-1], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    claim = dict(game_id=gid, status='dispatching', checkpoint_sha256=checkpoint,
                 request=request, source_sha256=meta['source_sha256'])
    path = Path(claim_path)
    # Exclusive file creation persists the no-replay decision before transport.
    with path.open('x', encoding='utf8') as handle:
        json.dump(claim, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    after = call(request['command'], request.get('options'))
    event = dict(request=request, response=after, status=200)
    checked = check_event(before, event, meta)
    claim.update(status='validated_received', check=checked)
    path.write_text(json.dumps(claim, indent=2, sort_keys=True), encoding='utf8')
    return dict(request=request, response=after, check=checked)


def _dig_price(options, request, proof_metadata):
    from fractions import Fraction
    args = request.get('options', {})
    bet = _native(args.get('bet'))
    if bet <= 0 or bet not in options.get('available_bets', []):
        raise ValueError('Dig audit bet outside received native whitelist')
    feature = args.get('purchased_feature')
    expected_keys = {'bet'}
    if feature is None:
        if set(args) != expected_keys:
            raise ValueError('Unproved normal Dig request fields')
        return bet
    expected_keys.add('purchased_feature')
    if feature not in ('freespin_chance', 'freespin_buy'):
        raise ValueError('Dig purchase outside exact source feature set')
    settings = options.get('feature_options', {})
    if feature in settings.get('disabled_features', []):
        raise ValueError('Disabled Dig feature was requested')
    multipliers = settings.get('feature_multipliers', {})
    factor = multipliers.get(feature)
    if isinstance(factor, dict):
        expected_keys.add('purchased_feature_level')
        level = args.get('purchased_feature_level')
        if type(level) is not str or level not in factor:
            raise ValueError('Dig purchase tier outside received whitelist')
        factor = factor[level]
    if set(args) != expected_keys or type(factor) is not int or factor <= 0:
        raise ValueError('Unproved Dig price/request fields')
    if (proof_metadata.get('source_sha256') != PINS['DigDigDigger']
        or proof_metadata.get('feature_default_base_bet') != 100
        or proof_metadata.get('price_rounding') != {'purchase': 'ceil', 'antebet': 'ceil'}):
        raise ValueError('Pinned Dig base-bet/ceiling source proof absent')
    base = multipliers.get('base_bet', 100)
    if type(base) is not int or base <= 0:
        raise ValueError('Dig native price denominator unproved')
    value = Fraction(bet * factor, base)
    return (value.numerator + value.denominator - 1) // value.denominator


def audit_dig(report):
    """Independent native replay, with failed anomalies retained and no outcome.win on gamble.

    Expected wallet/game accounting is never reset to an anomalous gameplay
    response. Only a subsequent explicit received FUN init establishes a separate
    baseline; any discontinuity is still emitted as a failed observation.
    """
    events = report.get('events', [])
    checks = []
    root_metadata = report.get('protocol_metadata', {})
    proof = root_metadata.get('dig_choice_source', {})
    try:
        if report.get('game', {}).get('game_id') != 'DigDigDigger' or _meta(proof) != 'DigDigDigger':
            raise ValueError('Dig-specific pinned audit proof required')
    except (ValueError, TypeError, KeyError) as error:
        checks.append(dict(kind='dig_audit_source', ok=False, reason=str(error)))
        return dict(game_id=report.get('game', {}).get('game_id'), status=report.get('status'),
                    events=len(events), checks=checks, passed=0, failed=1, modes_closed=0)
    previous = None
    expected_wallet = expected_game = None
    options = {}
    observations = []
    for index, event in enumerate(events):
        request = event.get('request', {})
        command = request.get('command')
        response = event.get('response')
        if event.get('status') != 200 or not isinstance(response, dict):
            checks.append(dict(event=index, kind='dig_received_status', ok=False,
                               reason='Rejected/uncertain response retained; no accepted state inferred'))
            continue
        try:
            wallet, game = _balance(response)
            if command == 'init':
                currency = response.get('options', {}).get('currency', {})
                if currency.get('code') != 'FUN' or currency.get('subunits') != 100:
                    raise ValueError('Dig audit init does not confirm original native FUN')
                if previous is not None:
                    same = ((wallet, game) == (expected_wallet, expected_game) or
                            (previous.get('flow', {}).get('state') == 'closed' and wallet + game == expected_wallet + expected_game))
                    observation = dict(event=index, kind='dig_explicit_init_balance_observation',
                        expected_native={'wallet': expected_wallet, 'game': expected_game},
                        actual_native={'wallet': wallet, 'game': game}, baseline_reset=True, ok=same,
                        note='Explicit non-wagering init baseline only; never a payout or superseding correction')
                    observations.append(observation)
                    checks.append(observation)
                else:
                    checks.append(dict(event=index, kind='dig_native_fun_init', ok=True))
                expected_wallet, expected_game = wallet, game
                options = response['options']
                previous = response
                continue
            if previous is None:
                raise ValueError('Dig audit action precedes native init')
            if command not in previous.get('flow', {}).get('available_actions', []):
                raise ValueError('Dig audit action not currently advertised')
            if command in ('gamble', 'close'):
                try:
                    checked = check_event(previous, event, proof)
                    checks.append(dict(event=index, **checked))
                except (ValueError, TypeError, KeyError) as error:
                    checks.append(dict(event=index, kind='dig_' + command + '_source_native_check', ok=False, reason=str(error)))
                if command == 'gamble':
                    marker = response.get('gamble', {}).get('win')
                    if type(marker) is not bool and not (type(marker) is int and marker >= 0):
                        raise ValueError('Unproved native Dig win marker')
                    choice = request.get('options', {}).get('bet')
                    expected_game = expected_game * (2 if choice in ('black', 'red') else 4) if bool(marker) else 0
                    valid = (wallet, game) == (expected_wallet, expected_game)
                else:
                    valid = wallet + game == expected_wallet + expected_game
                    if valid:
                        expected_wallet, expected_game = wallet, game
                checks.append(dict(event=index, kind='dig_expected_native_balance',
                    expected_native={'wallet': expected_wallet, 'game': expected_game},
                    actual_native={'wallet': wallet, 'game': game}, ok=valid))
            elif command == 'spin':
                if previous.get('flow', {}).get('state') not in ('closed', 'ready') or (previous.get('flow', {}).get('state') == 'ready' and expected_game != 0):
                    raise ValueError('New Dig paid spin before prior round closed/empty ready init')
                cost = _dig_price(options, request, root_metadata)
                feature = request.get('options', {}).get('purchased_feature')
                confirmed = response.get('flow', {}).get('purchased_feature', {})
                if feature and confirmed.get('name') != feature:
                    raise ValueError('Dig audit purchase not confirmed by native response')
                level = request.get('options', {}).get('purchased_feature_level')
                if level is not None and str(confirmed.get('level')) != level:
                    raise ValueError('Dig audit purchase tier not confirmed')
                win = _native(response.get('outcome', {}).get('win'))
                if response.get('outcome', {}).get('bet') != request['options']['bet']:
                    raise ValueError('Dig audit native base bet not confirmed')
                expected_wallet += expected_game - cost
                expected_game = win
                checks.append(dict(event=index, kind='dig_paid_native_balance', cost_native=cost,
                    win_native=win, expected_native={'wallet': expected_wallet, 'game': expected_game},
                    actual_native={'wallet': wallet, 'game': game}, ok=(wallet, game) == (expected_wallet, expected_game)))
            elif command in ('freespin', 'respin', 'play_bonus'):
                flow, prior = response.get('flow', {}), previous.get('flow', {})
                if flow.get('command') != command or flow.get('round_id') != prior.get('round_id') or flow.get('last_action_id') == prior.get('last_action_id'):
                    raise ValueError('Dig bonus continuation parent/action mismatch')
                win = _native(response.get('outcome', {}).get('win'))
                expected_game += win
                checks.append(dict(event=index, kind='dig_continuation_native_balance', win_native=win,
                    expected_native={'wallet': expected_wallet, 'game': expected_game},
                    actual_native={'wallet': wallet, 'game': game}, ok=(wallet, game) == (expected_wallet, expected_game)))
            else:
                raise ValueError('Unreviewed Dig audit command')
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            checks.append(dict(event=index, kind='dig_audit_contract', command=command, ok=False, reason=str(error)))
        # Phase/advertisement evidence advances, but monetary expectations remain
        # independent of actual balances until an explicit received init.
        previous = response
    return dict(game_id='DigDigDigger', status=report.get('status'), events=len(events),
                checks=checks, provider_state_observations=observations,
                passed=sum(c['ok'] is True for c in checks), failed=sum(c['ok'] is not True for c in checks),
                modes_closed=sum(m.get('status') == 'closed' for m in report.get('modes', [])))
