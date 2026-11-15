"""Classify the exact already-received Dig loss; never replay its gamble.

Default CLI is offline classification. --continue-remaining explicitly permits one
fresh native init and the unplayed declared purchases. Earlier failed checks and
the wallet discontinuity remain failed even if later modes reconcile.
"""
import copy
import json
from pathlib import Path
import time
from bonus_choices_extra import metadata, prepare, check_event
from resume_dig_choices import require_paused, pacing_delay, _archive_once
GID='DigDigDigger'
RECEIVED_SHA='0707775256f160cf939b307ff63f637a21f68f5ac1108f4481c3365a6756f8b7'


def classify_received(report, proof):
    events=report.get('events',[])
    if report.get('dig_received_loss_classified') or report.get('modes') or len(events)!=3 or report.get('game',{}).get('game_id')!=GID:
        raise ValueError('Only the exact unclassified three-event received Dig checkpoint is accepted')
    before=events[1]['response'];event=events[2];after=event.get('response',{})
    request=prepare(before,proof,'s')
    actual={k:v for k,v in event.get('request',{}).items() if k!='extra_data'}
    if (event.get('status')!=200 or event.get('response_sha256')!=RECEIVED_SHA or actual!=request
        or before.get('balance')!={'game':10,'wallet':99990}
        or after.get('balance')!={'game':0,'wallet':100000}
        or after.get('gamble')!={'history':['ac'],'value':['suit','s','c','a'],'bet':10,'win':0}
        or after.get('flow',{}).get('state')!='closed' or after['flow'].get('command')!='gamble'
        or after['flow'].get('round_id')!=before['flow']['round_id']
        or after['flow'].get('last_action_id')==before['flow']['last_action_id']):
        raise ValueError('Received Dig loss differs from pinned classified event; no normalization')
    try:check_event(before,event,proof)
    except ValueError as error:
        if 'balance/outcome mismatch' not in str(error):raise
    else:raise ValueError('Expected received financial anomaly is absent')
    report.setdefault('checks',[]).append(dict(kind='dig_received_gamble_financial_anomaly',event=2,
        expected_wallet_native=99990,actual_wallet_native=100000,wallet_delta_native=10,
        stake_native=10,payout_native=0,ok=False,source_win_value=0,
        note='Received loss is closed. Wallet discontinuity remains failed; cause/renewal attribution unproved.'))
    report['modes']=[dict(mode=copy.deepcopy(report['declared_modes'][0]),status='closed_financial_anomaly',
        round_status='closed',financial_status='failed',first_event=1,last_event=2,
        final_state='closed',final_balance=copy.deepcopy(after['balance']),resumed_existing_round=True,
        gamble_choices_executed=['s'],gamble_choices_financially_verified=[])]
    report['dig_received_loss_classified']=True
    report['dig_bonus_operations']=[dict(event=2,command='gamble',choice='s',status='received_source_classified',
        financial_status='failed',source_win_value=0,parent_round_closed=True,no_replay=True)]
    report['bonus_mode_coverage']=dict(source_types=proof['choices'],tested=['s'],
        executed_not_financially_verified=['s'],pending=[c for c in proof['choices'] if c!='s'],collect_tested=False)
    report['protocol_metadata']=dict(report.get('protocol_metadata',{}),dig_choices_helper_verified=True,dig_choice_source=copy.deepcopy(proof))
    report.update(status='needs_review',reason='Received Dig loss closed with unresolved native wallet discontinuity; earlier failed checks retained')
    return report


def _owned(demo,report,credentials):
    if (not credentials.get('fresh_demo') or credentials.get('game_id')!=GID
        or credentials.get('operation',{}).get('status')!='received' or credentials.get('series')!=demo.series
        or demo.clean.clean(copy.deepcopy(credentials.get('last_response')))!=report['events'][-1]['response']
        or demo.clean.clean(copy.deepcopy(demo.last_response))!=report['events'][-1]['response']):
        raise ValueError('Fresh owned received native/public checkpoint equality required')
    currency=report['events'][0]['response'].get('options',{}).get('currency',{})
    if currency.get('code')!='FUN' or currency.get('subunits')!=100:
        raise ValueError('Original native FUN currency required')


class _ReceivedGamble(Exception):
    def __init__(self,response):self.response=response


def continue_unplayed(demo,report,credentials,proof,*,persist=None):
    _owned(demo,report,credentials)
    if not report.get('dig_received_loss_classified') or report.get('remaining_baseline_observation') or len(report.get('modes',[]))!=1 or demo.last_response.get('flow',{}).get('state')!='closed':
        raise ValueError('Only newly classified closed loss may acquire a separate baseline once')
    persist=persist or (lambda:None)
    real_call,real_settle=demo.call,demo.settle
    demo.protocol_metadata=report['protocol_metadata']
    def save_progress():
        report.update(events=demo.events,checks=demo.money_checks,status='needs_review')
        persist()
    try:
        old=copy.deepcopy(demo.last_response)
        # Explicit single non-wagering observation, never a replacement for event 2.
        current=real_call('init')
        save_progress()
        currency=current.get('options',{}).get('currency',{})
        b=current.get('balance',{})
        if (currency.get('code')!='FUN' or currency.get('subunits')!=100
            or current.get('flow',{}).get('state') not in ('ready','closed')
            or 'spin' not in current.get('flow',{}).get('available_actions',[])
            or set(b)!={'game','wallet'} or any(type(b[k]) is not int or b[k]<0 for k in b) or b['game']!=0):
            raise ValueError('Fresh native init does not confirm empty ready/closed original FUN context')
        observation=dict(event=len(demo.events)-1,kind='native_init_balance_observation' if b==old['balance'] else 'native_init_balance_refresh',
            before_native=old['balance'],after_native=copy.deepcopy(b),source='explicit_non_wagering_init',
            note='Separate baseline for unplayed modes only. Earlier gameplay anomaly remains failed; no payout or superseding correction.')
        report['remaining_baseline_observation']=observation
        report.setdefault('provider_state_observations',[]).append(observation)
        demo.prev=current
        save_progress()
        local_choices=[]
        def checked_call(command,options=None):
            if command not in ('spin','freespin','respin','play_bonus','close','gamble'):
                raise ValueError('Received-loss recovery refuses guessed continuation')
            if command=='gamble':
                target=getattr(demo,'active_mode',{}).get('gamble_choice')
                if not getattr(demo,'active_mode',{}).get('conditional_card') or local_choices or target not in proof['choices'] or options!={'bet':target}:
                    raise ValueError('Only the current explicit conditional target may be attempted once; never replay historical gamble')
            before=copy.deepcopy(demo.last_response);index=len(demo.events)
            if command in ('close','gamble'):prepare(before,proof,'collect' if command=='close' else options['bet'])
            try:
                response=real_call(command,options)
                if command in ('close','gamble'):
                    q={'command':command}
                    if options is not None:q['options']=options
                    checked=check_event(before,dict(request=q,response=response,status=200),proof)
                    if command=='close':report['bonus_mode_coverage']['collect_tested']=True
                    else:
                        choice=options['bet'];local_choices.append(choice)
                        coverage=report['bonus_mode_coverage']
                        if choice not in coverage['tested']:coverage['tested'].append(choice)
                        verified=coverage.setdefault('financially_verified_choices',[])
                        if choice not in verified:verified.append(choice)
                        coverage['pending']=[c for c in proof['choices'] if c not in coverage['tested']]
                        report['dig_bonus_operations'].append(dict(event=index,command='gamble',choice=choice,status='received_native_validated',financial_status='verified',parent_mode=demo.active_mode['name']))
                elif command=='spin':
                    mode=demo.active_mode;expected=before['balance']['wallet']+(before['balance']['game'] if before['flow']['state']=='closed' else 0)-mode['cost_native'];actual=response.get('balance',{}).get('wallet')
                    if actual!=expected:raise ValueError('Unplayed Dig mode native debit mismatch')
                    checked=dict(kind='dig_unplayed_native_debit',expected=expected,actual=actual,ok=True)
                else:
                    expected=before['balance']['wallet'];actual=response.get('balance',{}).get('wallet')
                    if actual!=expected:raise ValueError('Dig continuation native wallet mismatch')
                    checked=dict(kind='dig_native_continuation_wallet',expected=expected,actual=actual,ok=True)
                demo.money_checks.append(dict(event=index,command=command,**checked));save_progress();return response
            except Exception:
                save_progress();raise
        def collect_settle(response):
            if response['flow']['state'] not in ('gamble','closed'):
                def intercept(command,options=None):
                    received=checked_call(command,options)
                    if received.get('flow',{}).get('state')=='gamble':raise _ReceivedGamble(received)
                    return received
                demo.call=intercept
                try:return real_settle(response)
                except _ReceivedGamble as reached:response=reached.response
                finally:demo.call=checked_call
            if response['flow']['state']=='gamble':
                mode=getattr(demo,'active_mode',{})
                if mode.get('conditional_card') and mode.get('gamble_choice') not in local_choices:
                    response=checked_call('gamble',{'bet':mode['gamble_choice']})
                if response['flow']['state']=='gamble':response=checked_call('close')
            if response['flow']['state']!='closed':raise ValueError('Unplayed Dig round did not close')
            return response
        demo.call,demo.settle=checked_call,collect_settle
        for mode in report['declared_modes'][1:]:
            local_choices.clear();start=len(demo.events)
            result=demo.run_mode(mode,report['events'][0]['response'])
            result['gamble_choices_executed']=list(local_choices)
            result['gamble_choices_financially_verified']=list(local_choices)
            if mode.get('conditional_card'):
                paid=sum(e.get('request',{}).get('command')=='spin' and e.get('status')==200 for e in demo.events[start:])
                if paid>1:raise ValueError('Conditional received-loss recovery exceeded one paid trigger')
                result.update(attempted_once=paid==1,paid_attempts=paid,conditional_choice=mode['gamble_choice'])
                if result.get('status')=='closed' and mode['gamble_choice'] not in local_choices:
                    result.update(status='needs_trigger',round_status='closed',reason='Single paid attempt did not offer the explicit target; never retried')
            report['modes'].append(result);save_progress()
            if result.get('status') not in ('closed','needs_trigger'):break
        report['remaining_declared_modes_status']='complete' if len(report['modes'])==len(report['declared_modes']) and all(m['status']=='closed' for m in report['modes'][1:]) else 'partial'
    except Exception as error:
        report['remaining_declared_modes_status']='needs_review'
        report['remaining_recovery_reason']=str(error) if isinstance(error,(RuntimeError,ValueError,KeyError)) else type(error).__name__
    finally:
        demo.call,demo.settle=real_call,real_settle
        save_progress()
    return report


def main(argv=None):
    import argparse
    from checkpoint_guard import acquire
    from legacy_recovery import restore
    from run_demo_qa import ROOT,PRIVATE,save,now
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--continue-remaining',action='store_true')
    parser.add_argument('--source',type=Path)
    args=parser.parse_args(argv)
    lock=acquire(ROOT/'runner.lock')
    state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
    require_paused(state,(ROOT/'STOP').read_text(encoding='utf8'))
    demo,report=restore(GID);credentials=json.loads((PRIVATE/(GID+'.session.json')).read_text(encoding='utf8'))
    _owned(demo,report,credentials)
    candidates=[args.source] if args.source else list((PRIVATE/'research/legacy'/GID).rglob('bundle.js'))
    if len(candidates)!=1:raise ValueError('One exact already-cached Dig bundle required')
    proof=metadata(GID,candidates[0].read_text(encoding='utf8'))
    pending=copy.deepcopy(report)
    already_classified=bool(report.get('dig_received_loss_classified'))
    if already_classified:
        if not args.continue_remaining or report.get('remaining_baseline_observation') or len(report.get('modes',[]))!=1:
            raise ValueError('Classified recovery already progressed; never repeat init or paid modes')
        suffix='.before-received-dig-remaining-after-classification'
    else:
        classify_received(pending,proof)
        suffix='.before-received-dig-loss-classification'
    archive=ROOT/'live/attempts'/(GID+suffix+'.json')
    private_archive=PRIVATE/'attempts'/(GID+suffix+'.session.json')
    if archive.exists() or private_archive.exists():raise RuntimeError('Received Dig recovery already attempted; never replay')
    delay=pacing_delay(state,time.time())
    _archive_once(archive,report);_archive_once(private_archive,credentials)
    report.clear();report.update(pending);demo.events=report['events'];demo.money_checks=report['checks']
    path=ROOT/'live'/(GID+'.json')
    def persist():report.update(events=demo.events,checks=demo.money_checks);save(path,report)
    persist()
    if args.continue_remaining:
        time.sleep(delay);state.update(active_game=GID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
        try:continue_unplayed(demo,report,credentials,proof,persist=persist)
        finally:
            report['finished_at']=now();persist();state['results'][GID]=dict(status='needs_review',modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+GID+'.json');state.update(active_game=None,updated_at=now());save(state_path,state)
    lock.close()
    print(GID,'received loss classified; financial anomaly retained;',report.get('remaining_declared_modes_status','remaining modes not executed'),flush=True)


if __name__=='__main__':main()
