"""Parent-only fresh FUN coverage of six finite Lucky Lady slot-card choices.

At most100 minimum default-line trigger spins; gross native debit budget includes
both trigger stakes and reserved prize stakes risked once. Every winning gamble
is immediately collected. No additional gamble level or unbounded search exists.
No transport or user-state writes occur during import or offline unit tests.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import urllib.request

from run_demo_qa import Demo, ROOT, PRIVATE, save, now
from run_wild_moon_manual import write_once, _private_scope
from bonus_choices_extra import PINS, CARDS, metadata, prepare, check_event
from classic_slots import metadata as slot_metadata
from old_slots import plan as slot_plan, paid_result

GID='LuckyLadyClover'
PIN=PINS[GID]
CONTEXT_ID='finite-cards'


def _native(value):
 if type(value) is not int or value<0:raise ValueError('Original nonnegative native FUN integer required')
 return value


def _proof(proof):
 if proof.get('game_id')!=GID or not proof.get('source_verified') or proof.get('source_sha256')!=PIN or proof.get('choices')!=list(CARDS):raise ValueError('Pinned six-choice Lucky Lady source required')


def cached_proofs():
 source=(PRIVATE/'research/classic/casino.min.js').read_bytes().decode('utf8')
 proof=metadata(GID,source);slot=slot_metadata(source,GID)
 return slot,proof


def minimum_trigger(initial,slot):
 if slot.get('source_sha256')!=PIN or slot.get('classic_game_id')!=GID:raise ValueError('Pinned classic slot money contract required')
 modes=slot_plan(initial,slot)
 candidates=[m for m in modes if m.get('name')=='normal/all_default_lines']
 if len(candidates)!=1:raise ValueError('One minimum native default-line trigger required')
 return copy.deepcopy(candidates[0])


def declared_choices(initial,slot,proof):
 _proof(proof);trigger=minimum_trigger(initial,slot)
 return [dict(name='semantic_card:'+choice,protocol='classic-finite-card',command='check_card',options={'bet':choice},
              trigger_mode=copy.deepcopy(trigger),source_sha256=PIN) for choice in CARDS]


def validate_original(old):
 if old.get('game',{}).get('game_id')!=GID or len(old.get('modes',[]))!=1 or old['modes'][0].get('status')!='closed' or old['modes'][0].get('mode',{}).get('name')!='normal/all_default_lines':raise ValueError('Original closed normal slot evidence required')
 if old.get('protocol_metadata',{}).get('source_sha256')!=PIN or old.get('events',[])[-1].get('request',{}).get('command')!='finish' or old['events'][-1].get('response',{}).get('game',{}).get('state')!='closed':raise ValueError('Original source-matching normal+finish checkpoint required')
 if any(c.get('ok') is False for c in old.get('checks',[])):raise ValueError('Original native discrepancy cannot be hidden by new context')


def _limits(max_attempts,budget,cost):
 if type(max_attempts) is not int or not 1<=max_attempts<=100:raise ValueError('Trigger attempt cap must be1..100')
 budget=100*cost if budget is None else budget
 if type(budget) is not int or not cost<=budget<=100*cost:raise ValueError('Gross native budget must fund one trigger and cannot exceed100 minimum trigger stakes')
 return budget


def run_choices(demo,initial,slot,proof,max_attempts=100,gross_native_budget=None,context=None,on_checkpoint=None,may_continue=None):
 """One source card action per qualifying winning round, then collect immediately."""
 _proof(proof);trigger=minimum_trigger(initial,slot);cost=trigger['cost_native'];budget=_limits(max_attempts,gross_native_budget,cost)
 declared=declared_choices(initial,slot,proof)
 context=context if context is not None else dict(game={'game_id':GID},context_id=CONTEXT_ID,modes=[],trigger_attempts=[])
 context.update(status='running',declared_modes=declared,limits={'max_attempts':max_attempts,'gross_native_budget':budget},gross_native_debit=0,executed_choices=[])
 context.setdefault('modes',[]);context.setdefault('trigger_attempts',[]);current=demo.prev or initial;covered=set()
 def checkpoint():
  context.update(events=copy.deepcopy(demo.events),checks=copy.deepcopy(demo.money_checks),executed_choices=[c for c in CARDS if c in covered])
  if on_checkpoint:on_checkpoint(context)
 def dispatch(request):
  nonlocal current
  response=demo.call(request['command'],request['options']) if 'options' in request else demo.call(request['command'])
  current=response;demo.prev=response;return response
 def collect():
  before=current;request=prepare(before,proof,'collect');index=len(demo.events);after=dispatch(request)
  demo.money_checks.append(dict(event=index,**check_event(before,dict(request=request,response=after,status=200),proof)))
  checkpoint()
 checkpoint()
 for attempt_number in range(1,max_attempts+1):
  if len(covered)==6 or context['gross_native_debit']+cost>budget or may_continue and not may_continue():break
  if current.get('game',{}).get('state') not in ('idle','closed') or 'spin' not in current.get('available_commands',[]):raise ValueError('New minimum spin requires natively closed prior round')
  if _native(current.get('balance'))<cost:break
  choice=next(c for c in CARDS if c not in covered);start=len(demo.events)
  record=dict(attempt=attempt_number,next_choice=choice,first_event=start,cost_native=cost,status='dispatching')
  context['trigger_attempts'].append(record);context['gross_native_debit']+=cost;checkpoint()
  before=current;after=dispatch({'command':'spin','options':trigger['options']})
  demo.money_checks.append(dict(event=start,**paid_result(before,after,trigger,slot)['check']))
  record.update(status='received',last_event=len(demo.events)-1);checkpoint()
  if after.get('game',{}).get('state')=='closed':record['status']='closed_no_trigger';continue
  if after.get('game',{}).get('state')!='check_card':raise ValueError('Received slot bonus requires separate review; no new trigger or guessed continuation')
  stake=_native(after.get('bets',{}).get('required_for_bonus_game',0))
  allowed=('check_card' in after.get('available_commands',[]) and stake>0 and stake<=after['balance']
           and context['gross_native_debit']+stake<=budget and (may_continue is None or may_continue()))
  if not allowed:
   record['choice_skipped_reason']='Native stake/advertisement/budget/stop gate does not allow another debit'
   collect();record.update(status='closed_collected_no_card',last_event=len(demo.events)-1);checkpoint();continue
  request=prepare(after,proof,choice);choice_event=len(demo.events);context['gross_native_debit']+=stake
  record.update(gamble_stake_native=stake,choice_status='dispatching');checkpoint()
  before=after;after=dispatch(request);checked=check_event(before,dict(request=request,response=after,status=200),proof)
  demo.money_checks.append(dict(event=choice_event,**checked));covered.add(choice)
  record.update(choice=choice,choice_event=choice_event,choice_status='validated_received');checkpoint()
  if after.get('game',{}).get('state')=='check_card':collect()
  if current.get('game',{}).get('state')!='closed':raise ValueError('Source card result did not close or collect')
  context['modes'].append(dict(mode=copy.deepcopy(declared[CARDS.index(choice)]),status='closed',first_event=start,last_event=len(demo.events)-1,
                               choice_event=choice_event,trigger_cost_native=cost,gamble_stake_native=stake,cost_native=cost+stake,
                               final_balance=current['balance'],final_state='closed'))
  record.update(status='closed_card',last_event=len(demo.events)-1);checkpoint()
 context['status']='complete_declared_modes' if len(covered)==6 and len(context['modes'])==6 else 'partial';checkpoint()
 return context


def audit_context(context,proof):
 """Independent actual-spin sums and source card conservation; no runner check trust."""
 _proof(proof);events=context.get('events',[]);checks=[];seen=set();choices={};closed_rounds={};round_start=None;card_used=False;attempts=gross=0
 if not events:return dict(game_id=GID,checks=[dict(kind='finite_native_init',ok=False)],passed=0,failed=1,complete=False,pending_choices=list(CARDS),executed_choices=[],paid_attempts=0,gross_native_debit=0)
 initial=events[0].get('response',{});o=initial.get('options',{});c=o.get('currency',{})
 if events[0].get('status')!=200 or events[0].get('request',{}).get('command')!='init' or c.get('code')!='FUN' or c.get('subunits')!=100:raise ValueError('Original accepted fresh native FUN init required')
 line=min(o['line_bets']);bets={str(i):line for i in range(len(o['lines']))};cost=sum(bets.values());limits=context.get('limits',{});max_attempts=limits.get('max_attempts',100);budget=_limits(max_attempts,limits.get('gross_native_budget'),cost)
 previous=initial;checks.append(dict(event=0,kind='finite_native_fun_init',ok=True))
 for index,event in enumerate(events[1:],1):
  q=event.get('request',{});r=event.get('response',{});command=q.get('command')
  try:
   if event.get('status')!=200 or r.get('errors'):raise ValueError('Uncertain/rejected input is not semantic coverage')
   if command not in previous.get('available_commands',[]):raise ValueError('Action was not natively advertised')
   if command=='spin':
    if round_start is not None or previous.get('game',{}).get('state') not in ('idle','closed') or q.get('options')!={'bets':bets}:raise ValueError('Only minimum native default-line trigger before closed round')
    win=0 if r.get('result') is None else _native(r['result'].get('total'));expected=_native(previous.get('balance'))-cost+win
    if _native(r.get('balance'))!=expected:raise ValueError('Independent native minimum-spin wallet mismatch')
    attempts+=1;gross+=cost;round_start=index;card_used=False
    if r.get('game',{}).get('state') not in ('check_card','closed'):raise ValueError('Unreviewed slot-bonus branch retained')
    checks.append(dict(event=index,kind='finite_minimum_spin_native_wallet',cost_native=cost,win_native=win,expected=expected,actual=r['balance'],ok=True))
   elif command in ('check_card','finish'):
    if round_start is None:raise ValueError('Card/finish lacks received minimum trigger')
    if command=='check_card':
     choice=q.get('options',{}).get('bet')
     if card_used or choice in seen:raise ValueError('Repeated semantic card or extra gamble level is outside finite plan')
     checked=check_event(previous,event,proof);gross+=checked['stake_native'];card_used=True;seen.add(choice)
     choices[choice]=dict(start=round_start,event=index)
    else:checked=check_event(previous,event,proof)
    checks.append(dict(event=index,**checked))
   else:raise ValueError('Unreviewed request or hidden FUN reset')
   if attempts>max_attempts or gross>budget:raise ValueError('Actual native debits exceed explicit bounded plan')
   if round_start is not None and r.get('game',{}).get('state')=='closed':closed_rounds[round_start]=index;round_start=None
   previous=r
  except (ValueError,KeyError,TypeError,AttributeError) as error:
   checks.append(dict(event=index,kind='finite_card_native_audit',ok=False,reason=str(error)));break
 valid=set()
 for item in context.get('modes',[]):
  if item.get('status')!='closed':continue
  mode=item.get('mode',{});choice=mode.get('options',{}).get('bet');received=choices.get(choice,{})
  ok=(choice in CARDS and choice not in valid and received.get('start')==item.get('first_event')
      and received.get('event')==item.get('choice_event') and closed_rounds.get(item.get('first_event'))==item.get('last_event'))
  checks.append(dict(event=item.get('last_event'),kind='finite_semantic_choice_receipt',choice=choice,ok=bool(ok)))
  if ok:valid.add(choice)
 failed=sum(x.get('ok') is not True for x in checks);pending=[choice for choice in CARDS if choice not in seen]
 return dict(game_id=GID,checks=checks,passed=sum(x.get('ok') is True for x in checks),failed=failed,paid_attempts=attempts,
             gross_native_debit=gross,executed_choices=[c for c in CARDS if c in seen],pending_choices=pending,
             complete=not failed and not pending and valid==set(CARDS) and round_start is None)


def derive_report(old,finite,proof):
 validate_original(old);audit=audit_context(finite,proof)
 return dict(game=copy.deepcopy(old['game']),protocol='lucky-lady-finite-contexts',status='complete_declared_modes' if audit['complete'] else 'partial',
             declared_modes=[dict(copy.deepcopy(m),context_id='original') for m in old.get('declared_modes',[])]+[dict(copy.deepcopy(m),context_id=CONTEXT_ID) for m in finite.get('declared_modes',[])],
             modes=[dict(copy.deepcopy(m),context_id='original') for m in old['modes']]+[dict(copy.deepcopy(m),context_id=CONTEXT_ID) for m in finite.get('modes',[])],
             contexts=[dict(context_id='original',report=copy.deepcopy(old)),dict(context_id=CONTEXT_ID,report=copy.deepcopy(finite))],
             protocol_metadata=dict(finite_card_source=copy.deepcopy(proof),context_scoped_events=True),finite_card_coverage=audit,
             original_normal_finish_preserved=True,note='Finite semantic choices only; native fresh contexts and aliases are never flattened or financially equated.')


def output_paths(root=ROOT):
 root=Path(root)
 return root/'live/bonus-contexts/LuckyLadyClover.finite-cards.context.json',root/'live/LuckyLadyClover.json'


def verify_fresh_source(demo,directory):
 if not getattr(demo.opener,'classic_casino',False):raise ValueError('Fresh official launch did not expose reviewed classic client')
 url='https://cdn.bgaming-network.com/html/casino.min.js'
 with demo.opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
  if response.url!=url:raise ValueError('Unexpected official classic source redirect')
  raw=response.read()
 proof=metadata(GID,raw.decode('utf8'));slot=slot_metadata(raw.decode('utf8'),GID)
 write_once(Path(directory)/'source/casino.min.js',raw);proof.update(source_url=url,source_bytes_sha256=hashlib.sha256(raw).hexdigest())
 return slot,proof


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true',required=True);p.add_argument('--max-attempts',type=int,default=100);p.add_argument('--gross-native-budget',type=int);args=p.parse_args()
 from checkpoint_guard import acquire,require_inactive
 from legacy_recovery import restore
 lock=acquire(ROOT/'runner.lock');state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'));require_inactive(state)
 stop_path=ROOT/'STOP';stop_value=stop_path.read_text(encoding='utf8').strip()
 if stop_value=='CONTINUE':raise RuntimeError('Pause shared queue before isolated finite slot-card run')
 private_context=PRIVATE/'finite-lucky-lady-cards';public_context,canonical=output_paths()
 if private_context.exists() or public_context.exists():raise RuntimeError('Once-only finite-card context exists; review received checkpoint instead of replay')
 old_demo,old=restore(GID);validate_original(old);slot,proof=cached_proofs()
 if old_demo.last_response.get('game',{}).get('state')!='closed':raise ValueError('Original normal slot round remains open')
 private_context.mkdir(parents=True,exist_ok=False)
 write_once(private_context/'original.session.json',(PRIVATE/(GID+'.session.json')).read_bytes());write_once(private_context/'run-state.before.json',state_path.read_bytes())
 write_once(ROOT/'live/attempts/LuckyLadyClover.before-finite-cards.json',canonical.read_bytes())
 while time.time()-state.get('last_launch_epoch',0)<60:
  if stop_path.read_text(encoding='utf8').strip()!=stop_value:raise RuntimeError('Stop gate changed before fresh launch')
  time.sleep(min(1,60-(time.time()-state.get('last_launch_epoch',0))))
 if stop_path.read_text(encoding='utf8').strip()!=stop_value:raise RuntimeError('Stop gate changed before fresh launch')
 state.update(active_game=GID,active_context_id=CONTEXT_ID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 demo=Demo(old['game']);finite=dict(game=copy.deepcopy(old['game']),context_id=CONTEXT_ID,status='starting',started_at=now(),modes=[],events=[],checks=[])
 def persist(context=None):
  finite.update(events=copy.deepcopy(demo.events),checks=copy.deepcopy(demo.money_checks))
  save(public_context,finite);save(canonical,derive_report(old,finite,proof))
 try:
  with _private_scope(private_context):
   initial=demo.launch();slot,proof=verify_fresh_source(demo,private_context);trigger=minimum_trigger(initial,slot)
   budget=_limits(args.max_attempts,args.gross_native_budget,trigger['cost_native'])
   if _native(initial.get('balance'))<budget:raise ValueError('Fresh native FUN cannot fund bounded gross debit plan')
   finite.update(protocol='legacy-v1-slots',bootstrap=copy.deepcopy(demo.bootstrap),protocol_metadata=dict(slot,finite_card_source=proof))
   demo.prev=initial
   run_choices(demo,initial,slot,proof,args.max_attempts,budget,finite,persist,lambda:stop_path.read_text(encoding='utf8').strip()==stop_value)
   if audit_context(finite,proof)['failed']:raise RuntimeError('Independent finite-card native audit failed; no further input')
 except Exception as error:
  finite.update(status='needs_review',error_type=type(error).__name__,reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else 'Launch/static/transport failure; no retry')
 finally:
  finite['finished_at']=now();persist();derived=derive_report(old,finite,proof)
  state['results'][GID]=dict(status=derived['status'],modes_closed=sum(m.get('status')=='closed' for m in derived['modes']),report='live/'+GID+'.json')
  state.update(active_game=None,updated_at=now());state.pop('active_context_id',None);save(state_path,state)
  print(GID,derived['status'],'finite choices',len(derived['finite_card_coverage']['executed_choices']))


if __name__=='__main__':main()
