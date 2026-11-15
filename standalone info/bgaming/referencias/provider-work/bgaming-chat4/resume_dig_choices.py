"""Explicit guarded DigDigDigger recovery. Importing this module performs no I/O/actions.

The CLI resumes the exact already-paid normal round, then remaining declared modes.
Optional --conditional-card-modes buys one native-minimum trigger attempt per choice;
no unoffered choice is retried. Parent owns source fallback and independent audit.
"""
import copy
import json
import math
from pathlib import Path
import time
from bonus_choices_extra import metadata, prepare, check_event
from checkpoint_guard import require_inactive

GID = 'DigDigDigger'


def require_paused(state, stop):
    require_inactive(state)
    if stop.strip() == 'CONTINUE':
        raise RuntimeError('Pause between games before recovering the existing round')


def pacing_delay(state, epoch):
    previous = state.get('last_launch_epoch', 0)
    if type(previous) not in (int, float) or not math.isfinite(previous) or previous > epoch:
        raise ValueError('Invalid/future game pacing timestamp; review before recovery')
    return max(0, 60 - (epoch - previous))


def validate_pending(demo, report, credentials, proof):
    events = report.get('events', [])
    modes = report.get('declared_modes', [])
    if (demo.game.get('game_id') != GID or report.get('game', {}).get('game_id') != GID
        or not credentials.get('fresh_demo') or credentials.get('game_id') != GID
        or credentials.get('operation', {}).get('status') != 'received'
        or credentials.get('series') != demo.series):
        raise ValueError('Only a received owned fresh DigDigDigger context can be recovered')
    if len(events) != 2 or report.get('modes') or not modes:
        raise ValueError('Recovery requires exact original init + paid normal response; never repeat a progressed run')
    initial = events[0]['response']
    currency = initial.get('options', {}).get('currency', {})
    if events[0]['request'].get('command') != 'init' or currency.get('code') != 'FUN' or currency.get('subunits') != 100:
        raise ValueError('Received native FUN init required')
    before = credentials.get('last_response')
    if demo.clean.clean(copy.deepcopy(before)) != events[-1]['response'] or demo.clean.clean(copy.deepcopy(demo.last_response)) != events[-1]['response']:
        raise ValueError('Private/public received checkpoints differ; no replay')
    normal = modes[0]
    bets = initial.get('options', {}).get('available_bets', [])
    if (not bets or any(type(b) is not int or b <= 0 for b in bets)
        or normal.get('command') != 'spin' or normal.get('options') != {'bet': min(bets)}
        or normal.get('cost_native') != min(bets)
        or events[-1]['request'].get('command') != 'spin'
        or events[-1]['request'].get('options') != normal['options'] or events[-1].get('status') != 200):
        raise ValueError('Original received trigger is not the native-minimum normal mode')
    expected = initial['balance']['wallet'] - normal['cost_native']
    if before.get('balance', {}).get('wallet') != expected or before.get('outcome', {}).get('bet') != min(bets) or before.get('outcome', {}).get('win') != before.get('balance', {}).get('game'):
        raise ValueError('Original paid native stake/prize reconciliation differs')
    if not report.get('checks') or any(c.get('ok') is not True for c in report['checks']):
        raise ValueError('Existing native checks failed or absent; no normalization')
    prepare(before, proof, proof['choices'][0])
    return copy.deepcopy(normal)


def conditional_modes(initial, proof):
    minimum = min(initial['options']['available_bets'])
    return [dict(name='conditional_card/' + choice, command='spin', options={'bet': minimum},
                 cost_native=minimum, conditional_card=True, gamble_choice=choice,
                 maximum_paid_attempts=1) for choice in proof['choices']]


class _GambleReached(Exception):
    def __init__(self, response):
        self.response = response


def execute(demo, report, credentials, proof, *, include_conditional=False, persist=None):
    """Injected execution core. Caller must hold lock/paused gate, archive and pace.

    All network operations, if explicitly executed later, go through restored
    demo.call and its private sending/received/uncertain checkpoint mechanism.
    persist() is called after every response/failure and accepted native check.
    Tests inject a local fake transport and an in-memory persistence callback.
    """
    normal = validate_pending(demo, report, credentials, proof)
    persist = persist or (lambda: None)
    initial = report['events'][0]['response']
    declared = copy.deepcopy(report['declared_modes'])
    if include_conditional:
        declared.extend(conditional_modes(initial, proof))
    report['declared_modes'] = declared
    report['protocol_metadata'] = dict(report.get('protocol_metadata', {}),
        dig_choices_helper_verified=True, dig_choice_source=copy.deepcopy(proof))
    demo.protocol_metadata = report['protocol_metadata']
    report['dig_bonus_operations'] = []
    tested = set()
    collected = False
    local_tested = []
    original_call, original_settle = demo.call, demo.settle

    def publish():
        report.update(events=demo.events, checks=demo.money_checks)
        report['bonus_mode_coverage'] = dict(
            source_types=list(proof['choices']), tested=[c for c in proof['choices'] if c in tested],
            pending=[dict(choice=c, reason='Not exercised in offered gamble states; no hidden trigger retries') for c in proof['choices'] if c not in tested],
            collect_tested=collected, collect_pending_reason=None if collected else 'No positive gamble state remained after bounded choices',
            conditional_policy='One paid native-minimum attempt per declared conditional choice; absent offer remains needs_trigger')
        persist()

    def instrumented_call(command, options=None):
        before = copy.deepcopy(demo.last_response)
        index = len(demo.events)
        if command not in ('gamble', 'close', 'spin', 'freespin', 'respin', 'play_bonus'):
            raise ValueError('Recovery refuses unreviewed command before transport')
        if command in ('gamble', 'close'):
            choice = 'collect' if command == 'close' else (options or {}).get('bet')
            requested = {'command': command}
            if options is not None:
                requested['options'] = options
            if requested != prepare(before, proof, choice):
                raise ValueError('Recovery choice fields differ from source before transport')
        elif command not in before.get('flow', {}).get('available_actions', []):
            raise ValueError('Recovery continuation is not currently advertised')
        if command == 'spin':
            mode = demo.active_mode
            if before['flow']['state'] != 'closed' or options != mode['options'] or type(mode['cost_native']) is not int or mode['cost_native'] <= 0:
                raise ValueError('Only one declared paid trigger from a closed round is allowed')
        report['dig_recovery_operation'] = dict(command=command, event=index, status='sending')
        publish()
        try:
            response = original_call(command, options)
        except Exception as error:
            report['dig_recovery_operation'].update(status='uncertain_or_rejected', error_type=type(error).__name__)
            publish()
            raise
        try:
            if command in ('gamble', 'close'):
                request = {'command': command}
                if options is not None:
                    request['options'] = options
                checked = check_event(before, dict(request=request, response=response, status=200), proof)
            elif command == 'spin':
                mode = demo.active_mode
                balance = before['balance']
                credit = balance['game'] if before['flow']['state'] == 'closed' else 0
                expected = balance['wallet'] + credit - mode['cost_native']
                actual = response.get('balance', {}).get('wallet')
                if type(actual) is not int or actual != expected:
                    raise ValueError('Dig paid native debit mismatch')
                feature = options.get('purchased_feature')
                offered = response.get('flow', {}).get('purchased_feature', {})
                if feature and offered.get('name') != feature:
                    raise ValueError('Dig declared feature not confirmed')
                if 'purchased_feature_level' in options and str(offered.get('level')) != str(options['purchased_feature_level']):
                    raise ValueError('Dig declared feature level not confirmed')
                checked = dict(kind='dig_native_paid_debit', expected=expected, actual=actual,
                               cost_native=mode['cost_native'], ok=True)
            elif command in ('freespin', 'respin', 'play_bonus'):
                expected = before['balance']['wallet']
                actual = response.get('balance', {}).get('wallet')
                if type(actual) is not int or actual != expected:
                    raise ValueError('Dig non-wagering continuation native wallet mismatch')
                checked = dict(kind='dig_native_continuation_wallet', expected=expected, actual=actual, ok=True)
            else:
                raise ValueError('Recovery helper refuses unreviewed commands')
            demo.money_checks.append(dict(event=index, command=command, **checked))
        except Exception as error:
            demo.money_checks.append(dict(kind='dig_native_check_failure', event=index,
                command=command, ok=False, error_type=type(error).__name__))
            report['dig_recovery_operation'].update(status='received_failed_validation')
            publish()
            raise
        report['dig_recovery_operation'].update(status='received_validated')
        publish()
        return response

    def settle_with_choices(response):
        nonlocal collected
        # Let existing settlement handle all other known states. Intercept only a
        # newly received gamble after its continuation wallet check was recorded.
        if response['flow']['state'] not in ('gamble', 'closed'):
            def stop_on_gamble(command, options=None):
                received = instrumented_call(command, options)
                if received.get('flow', {}).get('state') == 'gamble':
                    raise _GambleReached(received)
                return received
            demo.call = stop_on_gamble
            try:
                return original_settle(response)
            except _GambleReached as reached:
                response = reached.response
            finally:
                demo.call = instrumented_call
        if response['flow']['state'] == 'closed':
            return response
        target = getattr(demo, 'active_mode', {}).get('gamble_choice')
        choices = [target] if target is not None else [c for c in proof['choices'] if c not in tested]
        for choice in choices:
            if response['flow']['state'] == 'closed':
                break
            request = prepare(response, proof, choice)
            index = len(demo.events)
            response = instrumented_call(request['command'], request.get('options'))
            tested.add(choice)
            local_tested.append(choice)
            report['dig_bonus_operations'].append(dict(event=index, command='gamble', choice=choice,
                parent_mode=getattr(demo, 'active_mode', {}).get('name'), status='received_native_validated'))
            publish()
        if response['flow']['state'] != 'closed':
            request = prepare(response, proof, 'collect')
            index = len(demo.events)
            response = instrumented_call(request['command'])
            collected = True
            report['dig_bonus_operations'].append(dict(event=index, command='close',
                parent_mode=getattr(demo, 'active_mode', {}).get('name'), status='received_native_validated'))
            publish()
        if response['flow']['state'] != 'closed':
            raise ValueError('Dig round remains open after source close')
        return response

    demo.call, demo.settle = instrumented_call, settle_with_choices
    report.update(status='running')
    report.pop('reason', None)
    report.pop('error_type', None)
    try:
        demo.active_mode = normal
        response = settle_with_choices(demo.last_response)
        demo.prev = response
        report['modes'].append(dict(mode=normal, status='closed', first_event=1,
            last_event=len(demo.events)-1, final_balance=response['balance'], final_state='closed',
            resumed_existing_round=True, resumed_existing_purchase=False,
            gamble_choices_tested=list(local_tested)))
        publish()
        for mode in declared[1:]:
            local_tested.clear()
            attempt_start = len(demo.events)
            result = demo.run_mode(mode, initial)
            result['gamble_choices_tested'] = list(local_tested)
            if mode.get('conditional_card'):
                paid_attempts = sum(e.get('request', {}).get('command') == 'spin' and e.get('status') == 200 for e in demo.events[attempt_start:])
                if paid_attempts > 1:
                    raise ValueError('Conditional choice exceeded its single paid-attempt limit')
                result.update(attempted_once=paid_attempts == 1, paid_attempts=paid_attempts, conditional_choice=mode['gamble_choice'])
                if result.get('status') == 'closed' and mode['gamble_choice'] not in local_tested:
                    result.update(status='needs_trigger', round_status='closed',
                        reason='The single paid native-minimum attempt did not offer the targeted gamble choice; no retry')
            report['modes'].append(result)
            publish()
            if result.get('status') not in ('closed', 'needs_trigger'):
                break
        all_closed = len(report['modes']) == len(declared) and all(m['status'] == 'closed' for m in report['modes'])
        report['status'] = 'complete_declared_modes' if all_closed and set(proof['choices']) <= tested and collected else 'partial'
    except Exception as error:
        report.update(status='needs_review', reason=str(error) if isinstance(error, (RuntimeError, ValueError, KeyError)) else type(error).__name__)
    finally:
        demo.call, demo.settle = original_call, original_settle
        publish()
    return report


def _archive_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        import os
        os.fsync(handle.fileno())


def main(argv=None):
    import argparse
    from checkpoint_guard import acquire
    from legacy_recovery import restore
    from run_demo_qa import ROOT, PRIVATE, save, now
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conditional-card-modes', action='store_true')
    parser.add_argument('--source', type=Path, help='Already cached reviewed Dig bundle; never fetched')
    args = parser.parse_args(argv)
    runner_lock_handle = acquire(ROOT / 'runner.lock')
    state_path = ROOT / 'run-state.json'
    state = json.loads(state_path.read_text(encoding='utf8'))
    require_paused(state, (ROOT / 'STOP').read_text(encoding='utf8'))
    demo, report = restore(GID)
    credentials = json.loads((PRIVATE / (GID + '.session.json')).read_text(encoding='utf8'))
    candidates = [args.source] if args.source else list((PRIVATE / 'research/legacy' / GID).rglob('bundle.js'))
    if len(candidates) != 1:
        raise ValueError('Select exactly one already cached reviewed Dig source')
    proof = metadata(GID, candidates[0].read_text(encoding='utf8'))
    validate_pending(demo, report, credentials, proof)
    archive = ROOT / 'live/attempts' / (GID + '.before-dig-choice-recovery.json')
    private_archive = PRIVATE / 'attempts' / (GID + '.before-dig-choice-recovery.session.json')
    if archive.exists() or private_archive.exists():
        raise RuntimeError('Dig recovery previously attempted; review evidence instead of replaying')
    delay = pacing_delay(state, time.time())
    _archive_once(archive, copy.deepcopy(report))
    _archive_once(private_archive, credentials)
    time.sleep(delay)
    state.update(active_game=GID, last_launch_epoch=time.time(), updated_at=now())
    save(state_path, state)
    path = ROOT / 'live' / (GID + '.json')
    def persist():
        report.update(events=demo.events, checks=demo.money_checks)
        save(path, report)
    try:
        execute(demo, report, credentials, proof, include_conditional=args.conditional_card_modes, persist=persist)
    finally:
        report['finished_at'] = now()
        persist()
        state['results'][GID] = dict(status=report['status'], modes_closed=sum(m['status'] == 'closed' for m in report.get('modes', [])), report='live/' + GID + '.json')
        state.update(active_game=None, updated_at=now())
        save(state_path, state)
        runner_lock_handle.close()
    print(GID, report['status'], 'choices', report['bonus_mode_coverage']['tested'], 'collect', report['bonus_mode_coverage']['collect_tested'], flush=True)


if __name__ == '__main__':
    main()
