"""Explicit bounded finite Dig slot-card coverage in the same received FUN context.

No I/O on import. The parent-only CLI requires --execute, paused/inactive lock,
exact private/public ownership, cached full-source hash and once-only archives.
Historic failed finances remain failed. No init, purchase or repeated card level.
"""
import copy
import hashlib
import json
from pathlib import Path
import time

from bonus_choices_extra import CARDS,PINS,metadata,prepare,check_event,audit_dig

GID='DigDigDigger'
PIN=PINS[GID]
KEY='dig_finite_conditional'


def cached_proof():
 from run_demo_qa import PRIVATE
 paths=list((PRIVATE/'research/legacy'/GID).rglob('bundle.js'))
 if len(paths)!=1:raise ValueError('One exact cached Dig source required')
 return metadata(GID,paths[0].read_text(encoding='utf8'))


def _source(proof):
 if proof.get('game_id')!=GID or proof.get('source_sha256')!=PIN or not proof.get('source_verified') or proof.get('choices')!=list(CARDS):raise ValueError('Full pinned Dig source and six semantic choices required')


def _native(value):
 if type(value) is not int or value<0:raise ValueError('Original nonnegative native integer required')
 return value


def _balance(response):
 b=response.get('balance',{})
 if set(b)!={'wallet','game'}:raise ValueError('Original native wallet/game fields required')
 return _native(b['wallet']),_native(b['game'])


def _limits(max_attempts,gross_native_budget):
 if type(max_attempts) is not int or not 1<=max_attempts<=100:raise ValueError('Total trigger attempts must be1..100')
 if type(gross_native_budget) is not int or not 1<=gross_native_budget<=5000:raise ValueError('Total native gross risk budget must be1..5000')


def _digest(event):return hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate(report,last,proof,max_attempts=100,gross_native_budget=5000):
 _source(proof);_limits(max_attempts,gross_native_budget)
 if report.get('game',{}).get('game_id')!=GID or KEY in report:raise ValueError('Unattempted finite extension in original Dig report required; never retry')
 if report.get('protocol_metadata',{}).get('source_sha256')!=PIN or not report['protocol_metadata'].get('source_verified'):raise ValueError('Original pinned paid-slot source required')
 events=report.get('events',[])
 if not events or events[-1].get('status')!=200 or last.get('flow',{}).get('state')!='closed' or 'spin' not in last.get('flow',{}).get('available_actions',[]):raise ValueError('Only received closed owned context may open another minimum round')
 _balance(last);o=events[0]['response'].get('options',{});c=o.get('currency',{});bets=o.get('available_bets',[])
 if c.get('code')!='FUN' or c.get('subunits')!=100 or not bets or any(type(b) is not int or b<=0 for b in bets):raise ValueError('Native FUN whitelist required')
 bet=min(bets);targets={}
 for item in report.get('modes',[]):
  mode=item.get('mode',{})
  if not mode.get('conditional_card'):continue
  choice=mode.get('gamble_choice')
  if choice not in CARDS or choice in targets or mode.get('name')!='conditional_card/'+choice or mode.get('command')!='spin' or mode.get('options')!={'bet':bet} or mode.get('cost_native')!=bet or mode.get('maximum_paid_attempts')!=1:raise ValueError('Original conditional mode minimum wire differs')
  if item.get('status')=='closed':
   if choice not in item.get('gamble_choices_financially_verified',[]):raise ValueError('Closed conditional mode lacks verified choice; explicit review required')
  elif item.get('status')!='needs_trigger':raise ValueError('Only closed/no-trigger conditional records may be extended')
  elif 'attempts' in item:raise ValueError('Previously extended conditional record requires review, never replay')
  targets[choice]=item
 if set(targets)!=set(CARDS):raise ValueError('Exactly six existing finite conditional records required')
 return bet,{c:targets[c] for c in CARDS if targets[c]['status']=='needs_trigger'}


def audit_extension(report,proof):
 """Replay extension from its received closed baseline, without trusting checks."""
 _source(proof);plan=report.get(KEY,{});events=report.get('events',[]);checks=[];gross=paid=0;seen=set();start=plan.get('first_event');round_start=None;card_used=False
 def failed(reason,index=None):checks.append(dict(kind='dig_finite_native_audit',event=index,ok=False,reason=str(reason)))
 try:
  _limits(plan['max_attempts'],plan['gross_native_budget'])
  if type(start) is not int or not 1<=start<=len(events) or _digest(events[start-1])!=plan.get('baseline_sha256'):raise ValueError('Finite baseline checkpoint differs')
  previous=events[start-1]['response'];_balance(previous)
  if previous.get('flow',{}).get('state')!='closed':raise ValueError('Finite baseline is not received closed')
  options=events[0]['response']['options'];currency=options.get('currency',{});bets=options['available_bets']
  if currency.get('code')!='FUN' or currency.get('subunits')!=100 or not bets or any(type(v) is not int or v<=0 for v in bets):raise ValueError('Independent original FUN native whitelist required')
  bet=min(bets)
  if type(bet) is not int or bet<=0 or plan.get('minimum_bet_native')!=bet:raise ValueError('Native minimum stake differs')
  checks.append(dict(kind='dig_finite_closed_baseline',event=start-1,ok=True))
  for index,event in enumerate(events[start:],start):
   request=event.get('request',{});after=event.get('response',{});command=request.get('command');flow=after.get('flow',{});prior=previous.get('flow',{})
   if event.get('status')!=200 or after.get('errors') or command not in prior.get('available_actions',[]):raise ValueError('Uncertain/rejected/unadvertised input is not coverage')
   oldwallet,oldgame=_balance(previous);wallet,game=_balance(after)
   if command=='spin':
    actual={k:v for k,v in request.items() if k!='extra_data'}
    if round_start is not None or prior.get('state')!='closed' or actual!={'command':'spin','options':{'bet':bet}}:raise ValueError('Only source minimum spin after closed round')
    if flow.get('command')!='spin' or not flow.get('round_id') or flow.get('round_id')==prior.get('round_id') or not flow.get('last_action_id'):raise ValueError('New paid round/action receipt differs')
    outcome=after.get('outcome',{});win=_native(outcome.get('win'))
    if outcome.get('bet')!=bet or wallet!=oldwallet+oldgame-bet or game!=win:raise ValueError('Native paid wallet/held-prize mismatch')
    paid+=1;gross+=bet;round_start=index;card_used=False
    checked=dict(kind='dig_finite_minimum_native_debit',cost_native=bet,win_native=win,expected_wallet_native=oldwallet+oldgame-bet,actual_wallet_native=wallet,ok=True)
   elif command in ('gamble','close'):
    if round_start is None:raise ValueError('Continuation lacks paid trigger in this bounded extension')
    checked=check_event(previous,event,proof)
    if command=='gamble':
     choice=request.get('options',{}).get('bet')
     if card_used or choice in seen or choice not in plan.get('requested_choices',[]):raise ValueError('Repeated card level or already completed semantic target')
     gross+=oldgame;card_used=True;seen.add(choice)
   elif command in ('freespin','respin','play_bonus'):
    actual={k:v for k,v in request.items() if k!='extra_data'}
    if round_start is None or actual!={'command':command} or flow.get('command')!=command or flow.get('round_id')!=prior.get('round_id') or not flow.get('last_action_id') or flow.get('last_action_id')==prior.get('last_action_id'):raise ValueError('Unproved continuation request/round/action')
    win=_native(after.get('outcome',{}).get('win'))
    if wallet!=oldwallet or game!=oldgame+win:raise ValueError('Native free continuation conservation mismatch')
    checked=dict(kind='dig_finite_continuation_native_wallet',win_native=win,ok=True)
   else:raise ValueError('Init, purchase or unreviewed action in finite extension')
   checks.append(dict(event=index,**checked))
   if paid>plan['max_attempts'] or gross>plan['gross_native_budget']:raise ValueError('Native gross risk or paid attempts exceed bounded plan')
   if flow.get('state')=='closed':round_start=None
   previous=after
 except (ValueError,KeyError,TypeError,AttributeError) as error:failed(error,locals().get('index'))
 return dict(checks=checks,failed=sum(c.get('ok') is not True for c in checks),passed=sum(c.get('ok') is True for c in checks),
             paid_attempts=paid,gross_native_debit=gross,executed_choices=[c for c in CARDS if c in seen],round_open=round_start is not None)


def execute(demo,report,proof,*,max_attempts=100,gross_native_budget=5000,persist=None,may_continue=None):
 """Injected transport core; parent owns lock, exact restore, once archive and pace."""
 bet,targets=validate(report,demo.last_response,proof,max_attempts,gross_native_budget)
 persist=persist or (lambda:None);initial_count=len(demo.events);report['events']=demo.events;report['checks']=demo.money_checks
 plan=dict(status='running',first_event=initial_count,baseline_sha256=_digest(demo.events[-1]),minimum_bet_native=bet,
           max_attempts=max_attempts,gross_native_budget=gross_native_budget,gross_native_debit=0,paid_attempts=0,
           requested_choices=list(targets),completed_choices=[],pending_choices=list(targets),attempts=[],source_sha256=PIN)
 report[KEY]=plan
 # Keep the original result verbatim as the first attempt, including its reason.
 for item in targets.values():
  item['attempts']=[copy.deepcopy(item)]
 original_status=report.get('status');current=demo.last_response
 def publish():
  report.update(events=demo.events,checks=demo.money_checks,status='needs_review');persist()
 def send(command,options=None):
  nonlocal current
  before=current;index=len(demo.events)
  if command not in before.get('flow',{}).get('available_actions',[]):raise ValueError('Native command not currently advertised')
  if command=='spin':
   if options!={'bet':bet} or before['flow']['state']!='closed':raise ValueError('Only original minimum paid trigger')
   wallet,held=_balance(before)
   if wallet+held<bet:raise ValueError('Insufficient actual closed native funds')
  elif command in ('gamble','close'):
   choice=options['bet'] if command=='gamble' else 'collect'
   if prepare(before,proof,choice)!=dict(command=command,**({'options':options} if options is not None else {})):raise ValueError('Semantic continuation wire differs')
  elif command not in ('freespin','respin','play_bonus') or options is not None:raise ValueError('No purchases or guessed continuation fields')
  plan['operation']=dict(status='sending',event=index,command=command);publish()
  try:after=demo.call(command,options) if options is not None else demo.call(command)
  except Exception:
   plan['operation']['status']='uncertain_or_rejected';publish();raise
  current=after;demo.prev=after
  plan['operation']['status']='received_unvalidated';publish()
  checked=audit_extension(report,proof)
  if checked['failed']:raise ValueError('Independent extension native audit failed; received input retained without retry')
  demo.money_checks.append(copy.deepcopy(checked['checks'][-1]))
  plan['operation']['status']='received_validated';publish();return after
 publish()
 try:
  while plan['pending_choices'] and plan['paid_attempts']<max_attempts and plan['gross_native_debit']+bet<=gross_native_budget:
   if may_continue and not may_continue():plan['stop_reason']='Paused gate changed';break
   wallet,held=_balance(current)
   if wallet+held<bet:plan['stop_reason']='Insufficient actual native closed funds';break
   choice=plan['pending_choices'][0];item=targets[choice];start=len(demo.events)
   attempt=dict(first_event=start,next_choice=choice,cost_native=bet,status='sending',bounded_extension=True)
   plan['attempts'].append(attempt);plan['paid_attempts']+=1;plan['gross_native_debit']+=bet;publish()
   send('spin',{'bet':bet});selected=False
   for depth in range(501):
    state=current.get('flow',{}).get('state')
    if state=='closed':break
    if state=='gamble':
     stake=_balance(current)[1]
     allowed=(not selected and stake>0 and 'gamble' in current['flow'].get('available_actions',[]) and plan['gross_native_debit']+stake<=gross_native_budget and (may_continue is None or may_continue()))
     if allowed:
      plan['gross_native_debit']+=stake;attempt.update(gamble_event=len(demo.events),gamble_stake_native=stake);publish()
      send('gamble',{'bet':choice});selected=True
     else:
      if not selected:attempt['choice_skipped_reason']='Native gross budget, positive stake or stop gate does not allow card risk'
      send('close')
     continue
    actions=[a for a in current.get('flow',{}).get('available_actions',[]) if a!='init']
    if len(actions)!=1 or actions[0] not in ('freespin','respin','play_bonus'):raise ValueError('Unproved native slot continuation; received state retained')
    send(actions[0])
   else:raise ValueError('Finite continuation depth guard; no further input')
   if current.get('flow',{}).get('state')!='closed':raise ValueError('Finite attempt not closed')
   attempt.update(last_event=len(demo.events)-1,status='closed_card' if selected else 'closed_no_trigger',final_balance=copy.deepcopy(current['balance']))
   item['attempts'].append(copy.deepcopy(attempt))
   if selected:
    item.update(status='closed',round_status='closed',financial_status='verified',first_event=start,last_event=len(demo.events)-1,
                final_balance=copy.deepcopy(current['balance']),final_state='closed',paid_attempts=len(item['attempts']),
                gamble_choices_executed=[choice],gamble_choices_financially_verified=[choice],conditional_choice=choice,
                bounded_trigger_policy=dict(maximum_total_paid_attempts=max_attempts,maximum_total_gross_native_debit=gross_native_budget),
                completion_attempt=len(item['attempts'])-1)
    item.pop('reason',None);plan['completed_choices'].append(choice);plan['pending_choices'].remove(choice)
    coverage=report.setdefault('bonus_mode_coverage',{})
    for field in ('tested','financially_verified_choices'):
     values=coverage.setdefault(field,[])
     if choice not in values:values.append(choice)
    coverage['pending']=[c for c in CARDS if c not in coverage.get('tested',[])]
    report.setdefault('dig_bonus_operations',[]).append(dict(event=attempt['gamble_event'],command='gamble',choice=choice,parent_mode=item['mode']['name'],status='received_native_validated',financial_status='verified',bounded_finite_extension=True))
   publish()
  plan['status']='complete_finite_choices' if not plan['pending_choices'] else 'bounded_partial'
  if plan['pending_choices']:plan.setdefault('stop_reason','Total paid attempt or native gross risk cap reached')
 except Exception as error:
  plan.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else 'Transport failure retained; no retry',error_type=type(error).__name__)
 finally:
  plan['audit']=audit_extension(report,proof);plan['prior_report_status']=original_status
  report['remaining_declared_modes_status']='complete' if all(m.get('status')=='closed' for m in report.get('modes',[]) if m.get('mode',{}).get('conditional_card')) else 'partial'
  publish()
 return report


def main():
 import argparse
 from checkpoint_guard import acquire
 from legacy_recovery import restore
 from resume_dig_choices import require_paused,pacing_delay,_archive_once
 from resume_dig_received_closed import _owned
 from run_demo_qa import ROOT,PRIVATE,save,now
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true',required=True);parser.add_argument('--max-attempts',type=int,default=100);parser.add_argument('--gross-native-budget',type=int,default=5000);args=parser.parse_args()
 lock=acquire(ROOT/'runner.lock');state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'));stop_path=ROOT/'STOP';stop_value=stop_path.read_text(encoding='utf8');require_paused(state,stop_value)
 demo,report=restore(GID);credentials=json.loads((PRIVATE/(GID+'.session.json')).read_text(encoding='utf8'));_owned(demo,report,credentials);proof=cached_proof()
 validate(report,demo.last_response,proof,args.max_attempts,args.gross_native_budget)
 previous_audit=audit_dig(report)
 last_init=max(i for i,e in enumerate(report['events']) if e.get('request',{}).get('command')=='init')
 if any(not c['ok'] and c.get('event',-1)>last_init for c in previous_audit['checks']):raise ValueError('Existing native discrepancy after most recent explicit init requires review')
 archive=ROOT/'live/attempts/DigDigDigger.before-finite-conditional-choices.json';private_archive=PRIVATE/'attempts/DigDigDigger.before-finite-conditional-choices.session.json'
 if archive.exists() or private_archive.exists():raise RuntimeError('Finite extension already attempted; review received evidence instead of retrying')
 _archive_once(archive,report);_archive_once(private_archive,credentials)
 delay=pacing_delay(state,time.time())
 while delay>0:
  time.sleep(min(1,delay))
  if stop_path.read_text(encoding='utf8')!=stop_value:raise RuntimeError('Paused gate changed before continuation')
  delay=pacing_delay(state,time.time())
 require_paused(state,stop_path.read_text(encoding='utf8'));state.update(active_game=GID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 def persist():save(ROOT/'live/DigDigDigger.json',report)
 try:execute(demo,report,proof,max_attempts=args.max_attempts,gross_native_budget=args.gross_native_budget,persist=persist,may_continue=lambda:stop_path.read_text(encoding='utf8')==stop_value)
 finally:
  report['finished_at']=now();persist();state['results'][GID]=dict(status=report['status'],modes_closed=sum(m.get('status')=='closed' for m in report['modes']),report='live/DigDigDigger.json');state.update(active_game=None,updated_at=now());save(state_path,state);lock.close()
 print(GID,report['status'],report[KEY]['status'],'pending',report[KEY]['pending_choices'],flush=True)


if __name__=='__main__':main()
