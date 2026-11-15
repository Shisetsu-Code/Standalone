"""Resume Dig only after its exact already-received non-wagering close; never replay it.

Classify the paid level-one mode offline, then remaining declared slot purchases and
one-attempt conditional card modes. Historic normal monetary anomaly stays failed.
Optional --observe-init observes pending-credit settlement only when total native
balance is conserved; an unexplained refresh stops before any new paid mode.
"""
import copy
import json
from pathlib import Path
import time
from bonus_choices_extra import metadata,prepare,check_event,audit_dig,_dig_price,PINS
from resume_dig_choices import require_paused,pacing_delay,_archive_once
from resume_dig_received_closed import _owned,_ReceivedGamble
GID='DigDigDigger'
RECEIVED_SHA='ffed4eb1cd0320689b890f9a8842f0c102e4cd9a58c3e0d3d4937f8407da001f'


def classify_close(report,proof):
 events=report.get('events',[]);modes=report.get('modes',[]);declared=report.get('declared_modes',[])
 if (report.get('game',{}).get('game_id')!=GID or report.get('dig_received_close_classified') or len(events)!=17
     or len(modes)!=2 or len(declared)!=17 or report.get('remaining_recovery_reason')!='Continuation did not produce a new action'):
  raise ValueError('Only exact received seventeen-event level-one close checkpoint may resume')
 if proof.get('source_sha256')!=PINS[GID] or report.get('protocol_metadata',{}).get('source_sha256')!=PINS[GID]:raise ValueError('Pinned Dig source differs')
 mode=declared[2]
 if mode.get('name')!='freespin_buy:1' or mode.get('options')!={'bet':10,'purchased_feature':'freespin_buy','purchased_feature_level':'1'} or mode.get('cost_native')!=1100:raise ValueError('Pending paid level-one mode differs')
 last=events[-1];before=events[-2]['response'];after=last.get('response',{})
 if (last.get('status')!=200 or last.get('response_sha256')!=RECEIVED_SHA or last.get('request',{}).get('command')!='close'
     or before.get('flow',{}).get('state')!='gamble' or after.get('flow',{}).get('state')!='closed'
     or before.get('balance')!={'game':265,'wallet':98884} or after.get('balance')!=before['balance']):
  raise ValueError('Received native closed prize differs; no replay or balance normalization')
 checked=check_event(before,last,proof)
 starts=[i for i,e in enumerate(events) if e.get('request',{}).get('command')=='spin']
 if not starts or starts[-1]!=5 or events[5]['request'].get('options')!=mode['options']:raise ValueError('Already-paid level-one trigger bounds differ')
 native_audit=audit_dig(report)
 if any(c.get('event',-1)>=5 and not c['ok'] for c in native_audit['checks']):raise ValueError('Current paid mode source/native audit failed')
 for candidate in declared:
  if candidate.get('command')!='spin' or candidate.get('cost_native')!=_dig_price(events[0]['response']['options'],{'options':candidate.get('options',{})},report['protocol_metadata']):raise ValueError('Declared slot request/price differs from native/source contract')
  if candidate.get('conditional_card') and (candidate.get('gamble_choice') not in proof['choices'] or candidate.get('maximum_paid_attempts')!=1):raise ValueError('Unproved conditional slot choice policy')
 prior=events[4]['response']['balance'];win=after['balance']['wallet']+after['balance']['game']-prior['wallet']-prior['game']+mode['cost_native']
 if win!=265:raise ValueError('Received complete level-one native return differs')
 report.setdefault('checks',[]).append(dict(event=16,**checked,normalized_existing_received_close=True))
 report['modes'].append(dict(mode=copy.deepcopy(mode),status='closed',first_event=5,last_event=16,
  final_balance=copy.deepcopy(after['balance']),final_state='closed',win_native=win,
  normalized_existing_received_close=True,resumed_existing_purchase=True))
 report['dig_received_close_classified']=True
 report['received_close_classification']=dict(event=16,previous_reason=report.get('remaining_recovery_reason'),
  note='Non-wagering close may retain last_action_id. Same round/closed state and pending native balance conserved; never resent.')
 report.setdefault('dig_bonus_operations',[]).append(dict(event=16,command='close',parent_mode=mode['name'],status='received_native_validated',financial_status='verified',parent_round_closed=True,no_replay=True))
 report['bonus_mode_coverage']['collect_tested']=True
 report['remaining_declared_modes_status']='pending'
 report.update(status='needs_review',reason='Historic normal native wallet discontinuity remains failed; received level-one close classified without replay')
 return report


def execute(demo,report,credentials,proof,*,observe_init=False,persist=None):
 _owned(demo,report,credentials)
 classify_close(report,proof)
 persist=persist or (lambda:None)
 original_call,original_settle=demo.call,demo.settle
 demo.protocol_metadata=report['protocol_metadata'];demo.protocol_metadata['dig_choice_source']=proof
 original_count=len(demo.events);local_choices=[];first_paid=True
 def publish():report.update(events=demo.events,checks=demo.money_checks,status='needs_review');persist()
 publish()
 try:
  if observe_init:
   old=copy.deepcopy(demo.last_response);observed=original_call('init');publish()
   currency=observed.get('options',{}).get('currency',{});balance=observed.get('balance',{})
   if currency.get('code')!='FUN' or currency.get('subunits')!=100 or observed.get('flow',{}).get('state') not in ('ready','closed') or set(balance)!={'wallet','game'} or any(type(v) is not int or v<0 for v in balance.values()):raise ValueError('Explicit init does not confirm original empty-ready/closed native FUN context')
   same=sum(balance.values())==sum(old['balance'].values())
   obs=dict(event=len(demo.events)-1,kind='native_closed_init_balance_observation',before_native=old['balance'],after_native=copy.deepcopy(balance),ok=same,note='Separate explicit non-wagering observation. Pending-credit allocation may move once; unexplained total change never becomes a payout or correction.')
   report['dig_received_close_init_observation']=obs;report.setdefault('provider_state_observations',[]).append(obs);demo.money_checks.append(dict(obs))
   publish()
   if not same:raise ValueError('Explicit init changed native total; no paid continuation')
   source_options=report['events'][0]['response']['options']
   if any(observed['options'].get(k)!=source_options.get(k) for k in ('available_bets','feature_options')):raise ValueError('Fresh native bet/feature price whitelist differs')
   demo.prev=observed
  else:demo.prev=demo.last_response
  def checked_call(command,options=None):
   nonlocal first_paid
   if command not in ('spin','freespin','respin','play_bonus','gamble','close'):raise ValueError('Unreviewed slot continuation blocked before transport')
   before=copy.deepcopy(demo.last_response);index=len(demo.events)
   if first_paid and (command!='spin' or options!=report['declared_modes'][3]['options']):raise ValueError('Recovery begins only with unplayed level-two purchase; no received close/trigger replay')
   if command not in before.get('flow',{}).get('available_actions',[]):raise ValueError('Slot command not currently advertised')
   if command=='gamble':
    target=getattr(demo,'active_mode',{}).get('gamble_choice')
    if not getattr(demo,'active_mode',{}).get('conditional_card') or local_choices or options!={'bet':target}:raise ValueError('Only explicit current conditional choice once is allowed')
    prepare(before,proof,target)
   elif command=='close':prepare(before,proof,'collect')
   elif command=='spin':
    mode=demo.active_mode
    if options!=mode['options'] or mode['cost_native']!=_dig_price(report['events'][0]['response']['options'],{'options':options},report['protocol_metadata']):raise ValueError('Unplayed native slot request/price differs')
   report['received_close_recovery_operation']=dict(event=index,command=command,status='sending');publish()
   try:response=original_call(command,options) if options is not None else original_call(command)
   except Exception as error:report['received_close_recovery_operation'].update(status='uncertain_or_rejected',error_type=type(error).__name__);publish();raise
   first_paid=False
   try:
    if command in ('gamble','close'):
     q={'command':command}
     if options is not None:q['options']=options
     check=check_event(before,{'request':q,'response':response,'status':200},proof)
     if command=='gamble':
      choice=options['bet'];local_choices.append(choice);coverage=report['bonus_mode_coverage']
      if choice not in coverage['tested']:coverage['tested'].append(choice)
      verified=coverage.setdefault('financially_verified_choices',[])
      if choice not in verified:verified.append(choice)
      coverage['pending']=[c for c in proof['choices'] if c not in coverage['tested']]
      report['dig_bonus_operations'].append(dict(event=index,command=command,choice=choice,parent_mode=demo.active_mode['name'],status='received_native_validated',financial_status='verified'))
     else:report['bonus_mode_coverage']['collect_tested']=True
    else:
     expected=before['balance']['wallet']
     if command=='spin':expected+=(before['balance']['game'] if before['flow']['state']=='closed' else 0)-demo.active_mode['cost_native']
     actual=response.get('balance',{}).get('wallet')
     if type(actual) is not int or actual!=expected:raise ValueError('Remaining slot native wallet reconciliation failed')
     check=dict(kind='dig_remaining_paid_debit' if command=='spin' else 'dig_native_continuation_wallet',expected=expected,actual=actual,ok=True)
    demo.money_checks.append(dict(event=index,command=command,**check));report['received_close_recovery_operation']['status']='received_validated';publish();return response
   except Exception as error:demo.money_checks.append(dict(event=index,command=command,kind='dig_remaining_native_failure',ok=False,error_type=type(error).__name__));publish();raise
  def slot_settle(response):
   if response['flow']['state'] not in ('closed','gamble'):
    def intercept(command,options=None):
     received=checked_call(command,options)
     if received.get('flow',{}).get('state')=='gamble':raise _ReceivedGamble(received)
     return received
    demo.call=intercept
    try:return original_settle(response)
    except _ReceivedGamble as reached:response=reached.response
    finally:demo.call=checked_call
   if response['flow']['state']=='gamble':
    mode=getattr(demo,'active_mode',{})
    if mode.get('conditional_card') and not local_choices:response=checked_call('gamble',{'bet':mode['gamble_choice']})
    if response['flow']['state']=='gamble':response=checked_call('close')
   if response['flow']['state']!='closed':raise ValueError('Remaining slot round did not close')
   return response
  demo.call,demo.settle=checked_call,slot_settle
  for mode in report['declared_modes'][3:]:
   local_choices.clear();start=len(demo.events);result=demo.run_mode(mode,report['events'][0]['response']);result['gamble_choices_executed']=list(local_choices);result['gamble_choices_financially_verified']=list(local_choices)
   if mode.get('conditional_card'):
    paid=sum(e.get('status')==200 and e.get('request',{}).get('command')=='spin' for e in demo.events[start:])
    if paid>1:raise ValueError('Conditional slot choice exceeded one paid attempt')
    result.update(paid_attempts=paid,attempted_once=paid==1,conditional_choice=mode['gamble_choice'])
    if result.get('status')=='closed' and mode['gamble_choice'] not in local_choices:result.update(status='needs_trigger',round_status='closed',reason='One paid attempt did not offer explicit target; no retry')
   report['modes'].append(result);report['received_close_recovery_audit']=audit_dig(report);publish()
   if any(c.get('event',-1)>=original_count and not c['ok'] for c in report['received_close_recovery_audit']['checks']):raise ValueError('Independent new slot action audit failed; no more paid modes')
   if result['status'] not in ('closed','needs_trigger'):break
  report['remaining_declared_modes_status']='complete' if len(report['modes'])==17 and all(m['status']=='closed' for m in report['modes'][3:]) else 'partial'
 except Exception as error:report['remaining_declared_modes_status']='needs_review';report['remaining_recovery_reason']=str(error) if isinstance(error,(RuntimeError,ValueError,KeyError)) else type(error).__name__
 finally:demo.call,demo.settle=original_call,original_settle;publish()
 return report


def main():
 import argparse
 from checkpoint_guard import acquire
 from legacy_recovery import restore
 from run_demo_qa import ROOT,PRIVATE,save,now
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--observe-init',action='store_true');args=parser.parse_args()
 lock=acquire(ROOT/'runner.lock');state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'));require_paused(state,(ROOT/'STOP').read_text(encoding='utf8'))
 demo,report=restore(GID);credentials=json.loads((PRIVATE/(GID+'.session.json')).read_text(encoding='utf8'));_owned(demo,report,credentials)
 sources=list((PRIVATE/'research/legacy'/GID).rglob('bundle.js'))
 if len(sources)!=1:raise ValueError('One exact cached Dig bundle required')
 proof=metadata(GID,sources[0].read_text(encoding='utf8'));preview=copy.deepcopy(report);classify_close(preview,proof)
 archive=ROOT/'live/attempts'/(GID+'.before-received-close-finish.json');backup=PRIVATE/'attempts'/(GID+'.before-received-close-finish.session.json')
 if archive.exists() or backup.exists():raise RuntimeError('Received close recovery already attempted; no replay')
 _archive_once(archive,report);_archive_once(backup,credentials)
 time.sleep(pacing_delay(state,time.time()));require_paused(state,(ROOT/'STOP').read_text(encoding='utf8'));state.update(active_game=GID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 path=ROOT/'live'/(GID+'.json')
 def persist():save(path,report)
 try:execute(demo,report,credentials,proof,observe_init=args.observe_init,persist=persist)
 finally:
  report['finished_at']=now();persist();state['results'][GID]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+GID+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);lock.close()
 print(GID,report['status'],'remaining',report.get('remaining_declared_modes_status'),'choices',report['bonus_mode_coverage']['tested'],flush=True)


if __name__=='__main__':main()
