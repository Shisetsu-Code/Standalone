"""Bounded, explicitly authorized FUN attempts for unmet source-native choices.

No work on import. Existing d.run_mode owns all wires/choices/reconciliation.
The instance call guard caps gross native debits, records every response, and
never retries transport, rejection, validation, or unresolved-state failures.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit

PROTOCOLS=('blackjack-extra','native-rocket-dice')

def _terminal(protocol,gid,response):
 if protocol=='blackjack-extra':
  from blackjack_extra import terminal
  return terminal(gid,response)
 from native_tables_extra import dice_terminal
 return dice_terminal(response)

def validate_report(report):
 protocol=report.get('protocol');gid=report.get('game',{}).get('game_id');meta=report.get('protocol_metadata',{});events=report.get('events',[])
 if protocol not in PROTOCOLS or report.get('status')!='partial' or not events or events[0].get('request',{}).get('command')!='init':raise ValueError('Only partial source-native blackjack/Rocket reports are eligible')
 currency=events[0]['response'].get('options',{}).get('currency',{})
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Exploration is restricted to original native FUN units')
 if any(c.get('ok') is False for c in report.get('checks',[])) or any(e.get('status')!=200 or e.get('response',{}).get('errors') for e in events):raise ValueError('Failed/rejected/uncertain evidence forbids conditional retry')
 modes=report.get('modes',[]);declared=report.get('declared_modes',[])
 if not modes or len(modes)!=len(declared) or any(m.get('mode')!=declared[i] or m.get('status') not in ('closed','needs_trigger') for i,m in enumerate(modes)):raise ValueError('Every declared mode must already have one completed paid attempt')
 if not any(m['status']=='needs_trigger' for m in modes):raise ValueError('No unmet trigger modes remain')
 if meta.get('protocol')!=protocol or meta.get('game_id')!=gid or not re.fullmatch('[a-f0-9]{64}',meta.get('source_sha256','')):raise ValueError('Original source metadata identity missing')
 if any(m['mode'].get('protocol')!=protocol or m['mode'].get('source_sha256')!=meta['source_sha256'] for m in modes):raise ValueError('Mode source identity differs')
 if not _terminal(protocol,gid,events[-1]['response']):raise ValueError('Last real native response is unresolved; no new wager allowed')
 return protocol,gid,events[0]['response']

def verify_source(report,fetch,guard=lambda:None):
 """Fresh original bytes only; never use load_client's on-disk cache as fresh."""
 old=report['protocol_metadata'];gid=report['game']['game_id'];protocol=report['protocol'];url=old['source_url'];u=urlsplit(url)
 if u.scheme!='https' or u.hostname!='cdn.bgaming-network.com' or u.query or u.fragment:raise ValueError('Unproved original source URL')
 checks=[]
 if old.get('client_family')=='classic-casino':
  if url!='https://cdn.bgaming-network.com/html/casino.min.js':raise ValueError('Classic source URL differs')
 elif old.get('loader_sha256'):
  base='https://cdn.bgaming-network.com/html/'+gid+'/';expected=base+old['client_version']+'/bundle.js'
  if url!=expected:raise ValueError('Versioned source URL differs')
  guard();loader=fetch(base+'loader.js')
  if not isinstance(loader,bytes) or hashlib.sha256(loader).hexdigest()!=old['loader_sha256']:raise ValueError('Fresh loader hash changed')
  from legacy_metadata import client_route
  version,route=client_route(loader.decode('utf8'))
  if version!=old['client_version'] or base+route!=url:raise ValueError('Fresh loader no longer selects the original source')
  checks.append(dict(url=base+'loader.js',sha256=old['loader_sha256']))
 else:raise ValueError('Original loader/classic source proof missing')
 guard();raw=fetch(url)
 if not isinstance(raw,bytes) or hashlib.sha256(raw).hexdigest()!=old['source_sha256']:raise ValueError('Fresh source hash differs from original report')
 if protocol=='blackjack-extra':
  from blackjack_extra import metadata,plan
 elif protocol=='native-rocket-dice':
  from native_tables_extra import metadata,plan
 else:raise ValueError('Unsupported conditional protocol')
 meta=metadata(raw.decode('utf8'),gid);declared=plan(report['events'][0]['response'],meta)
 if meta['protocol']!=protocol or declared!=report['declared_modes']:raise ValueError('Fresh source-derived mode catalog differs from original native plan')
 checks.append(dict(url=url,sha256=old['source_sha256']))
 return dict(fresh_source_verified=True,game_id=gid,protocol=protocol,source_sha256=old['source_sha256'],original_metadata_preserved=True,checks=checks)

def _request_cost(protocol,gid,request,initial,current,mode,paid_seen):
 if protocol=='blackjack-extra':
  from blackjack_extra import request_cost
  return request_cost(gid,request,initial,current)
 if request['command']==mode['command']:
  if paid_seen or request.get('options')!=mode['options']:raise ValueError('Unexpected extra paid Rocket request')
  return mode['cost_native']
 return 0

def _original_attempt(report,item,protocol,gid,initial):
 start=item.get('first_event');end=item.get('last_event');events=report['events'];mode=item['mode']
 if type(start) is not int or type(end) is not int or not 0<start<=end<len(events):raise ValueError('Original native attempt event bounds missing')
 cost=0;current=events[start-1]['response'];paid=False
 for event in events[start:end+1]:
  debit=_request_cost(protocol,gid,event['request'],initial,current,mode,paid)
  cost+=debit;paid=paid or event['request']['command']==mode['command'];current=event['response']
 if not _terminal(protocol,gid,current):raise ValueError('Original unmet mode is not a terminal attempt')
 return dict(kind='original_recorded_attempt',mode_target=mode.get('target',mode.get('risk_chosen',mode['name'])),first_event=start,last_event=end,cost_native=cost,status=item['status'],result=copy.deepcopy(item))

def preserve_native_checkpoint(demo,operation):
 """Keep received/rejected/uncertain transport truth through helper snapshots."""
 native_checkpoint=demo.checkpoint;latest=copy.deepcopy(operation)
 def tracked_native(operation):
  nonlocal latest
  latest=copy.deepcopy(operation);return native_checkpoint(operation)
 demo.checkpoint=tracked_native
 def snapshot(stage):return native_checkpoint(dict(latest,conditional_exploration_stage=stage))
 return snapshot

def explore(demo,report,*,authorized,max_additional_attempts=20,max_debit_native,gate,checkpoint,fetch_source,mode_names=None):
 if authorized is not True or type(max_additional_attempts) is not int or not 1<=max_additional_attempts<=100 or type(max_debit_native) is not int or max_debit_native<=0:raise ValueError('Explicit FUN exploration authorization, 1..100 attempts and positive native debit budget required')
 protocol,gid,initial=validate_report(report);gate.check();proof=verify_source(report,fetch_source,gate.check)
 current=getattr(demo,'last_response',None) or getattr(demo,'prev',None)
 if not current or not _terminal(protocol,gid,current):raise ValueError('Restored own native context is not terminal')
 result=copy.deepcopy(report);demo.events=result['events'];demo.money_checks=result.setdefault('checks',[]);demo.prev=current;demo.protocol_metadata=copy.deepcopy(report['protocol_metadata'])
 eligible=[i for i,m in enumerate(result['modes']) if m['status']=='needs_trigger']
 if mode_names is not None:
  wanted=set(mode_names)
  if not wanted or wanted-set(result['modes'][i]['mode']['name'] for i in eligible):raise ValueError('Only existing needs_trigger mode names may be selected')
  eligible=[i for i in eligible if result['modes'][i]['mode']['name'] in wanted]
 policy=dict(user_authorized_exploratory_scope='official_suite_owned_FUN_only',protocol=protocol,max_additional_attempts_per_mode=max_additional_attempts,max_gross_debit_native=max_debit_native,gross_debit_native=0,additional_attempts=0,selected_modes=[result['modes'][i]['mode']['name'] for i in eligible],source_verification=proof)
 result['conditional_exploration']=policy;result['status']='running'
 def persist(stage,attempt=None):
  result['events']=demo.events;result['checks']=demo.money_checks
  checkpoint(stage,dict(report=copy.deepcopy(result),attempt=copy.deepcopy(attempt),gross_debit_native=policy['gross_debit_native']))
 persist('source_verified')
 stopped=False
 for index in eligible:
  item=result['modes'][index];mode=copy.deepcopy(item['mode']);attempts=copy.deepcopy(item.get('attempts',[])) or [_original_attempt(report,item,protocol,gid,initial)]
  item['attempts']=attempts
  for number in range(1,max_additional_attempts+1):
   gate.check()
   if policy['gross_debit_native']+mode['cost_native']>max_debit_native:policy['stop_reason']='native_debit_budget_exhausted';stopped=True;break
   if not _terminal(protocol,gid,demo.prev):raise ValueError('Current native round is pending before a paid attempt')
   attempt=dict(kind='additional_authorized_attempt',ordinal=number,mode_target=mode.get('target',mode.get('risk_chosen',mode['name'])),mode_name=mode['name'],first_event=len(demo.events),last_event=None,cost_native=0,status='started')
   attempts.append(attempt);policy['additional_attempts']+=1;persist('before_mode',attempt)
   original_call=demo.call;raw_current=demo.prev;paid_seen=False
   def guarded_call(command,options=None):
    nonlocal raw_current,paid_seen
    gate.check()
    if any(c.get('ok') is False for c in demo.money_checks):raise ValueError('Failed native validation forbids another request')
    request={'command':command}
    if options is not None:request['options']=options
    debit=_request_cost(protocol,gid,request,initial,raw_current,mode,paid_seen)
    if type(debit) is not int or debit<0:raise ValueError('Unproved native request debit')
    if policy['gross_debit_native']+debit>max_debit_native:raise RuntimeError('Native gross debit budget would be exceeded; pending state preserved')
    policy['gross_debit_native']+=debit;attempt['cost_native']+=debit;paid_seen=paid_seen or command==mode['command'];persist('before_request',attempt)
    try:response=original_call(command,options) if options is not None else original_call(command)
    except Exception:
     attempt['last_event']=len(demo.events)-1;persist('request_uncertain_or_rejected',attempt);raise
    raw_current=response;attempt['last_event']=len(demo.events)-1;persist('response_received_pending_native_validation',attempt)
    if not isinstance(response,dict) or response.get('errors') or not demo.events or demo.events[-1].get('status')!=200:raise ValueError('Rejected or malformed received response forbids retry')
    return response
   demo.call=guarded_call
   try:
    outcome=demo.run_mode(copy.deepcopy(mode),initial)
    if any(c.get('ok') is False for c in demo.money_checks) or not _terminal(protocol,gid,demo.prev):raise ValueError('Conditional attempt did not finish with fully verified terminal native evidence')
    attempt.update(status=outcome['status'],last_event=len(demo.events)-1,result=copy.deepcopy(outcome))
    if outcome['status']=='closed':
     result['modes'][index]=dict(copy.deepcopy(outcome),attempts=attempts);persist('target_closed',attempt);break
    if outcome['status']!='needs_trigger':policy['stop_reason']=outcome['status'];stopped=True;persist('mode_stopped_without_retry',attempt);break
    persist('after_unreached_terminal_mode',attempt)
   except Exception as error:
    attempt.update(status='validation_failed_or_uncertain',last_event=len(demo.events)-1,error_type=type(error).__name__)
    demo.money_checks.append(dict(kind='conditional_attempt_failure',mode_name=mode['name'],error_type=type(error).__name__,ok=False));result['status']='needs_review';policy['stop_reason']='received_or_uncertain_attempt_requires_review';persist('attempt_failed_no_retry',attempt);stopped=True;break
   finally:demo.call=original_call
  if stopped:break
 if result['status']!='needs_review':result['status']='complete_declared_modes' if all(m['status']=='closed' for m in result['modes']) and not report['protocol_metadata'].get('unresolved') else 'partial'
 persist('exploration_finished');return result

def run(gid,*,authorized=False,max_additional_attempts=20,max_debit_native,mode_names=None):
 """Parent CLI entry; restores only received own legacy sessions, never Hyper/HAR."""
 if authorized is not True or type(max_additional_attempts) is not int or not 1<=max_additional_attempts<=100 or type(max_debit_native) is not int or max_debit_native<=0 or not re.fullmatch('[A-Za-z0-9_-]+',gid):raise ValueError('Explicit bounded FUN authorization required')
 from run_demo_qa import ROOT,PRIVATE,save,now
 from checkpoint_guard import acquire,require_inactive
 from legacy_recovery import restore
 from all_lucky_variants import VariantGate,official_url
 lock=acquire(ROOT/'runner.lock');started=False;result=None;demo=None
 try:
  state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
  if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause under exact CHECKPOINT_MAINTENANCE before isolated exploration')
  path=ROOT/'live'/f'{gid}.json';raw=path.read_bytes();original=json.loads(raw);validate_report(original)
  session_path=PRIVATE/f'{gid}.session.json';session_raw=session_path.read_bytes();session=json.loads(session_raw)
  if session.get('fresh_demo') is not True or session.get('game_id')!=gid or session.get('operation',{}).get('status')!='received' or session.get('public_events')!=original['events']:raise ValueError('Only exact received own FUN context may be restored')
  work=PRIVATE/'conditional-mode-retries'/gid;archive=ROOT/'live/attempts'/f'{gid}.before-conditional-retries.json';private_archive=PRIVATE/'attempts'/f'{gid}.before-conditional-retries.session.json'
  if archive.exists() or private_archive.exists() or (work/'attempt.json').exists():raise ValueError('Existing bounded exploration requires review; no replay')
  demo,restored=restore(gid)
  if restored!=original:raise ValueError('Restored report changed')
  demo.opener.classic_casino=original['protocol_metadata'].get('client_family')=='classic-casino';demo.opener.classic_version=original['protocol_metadata'].get('client_version')
  native_snapshot=preserve_native_checkpoint(demo,session['operation'])
  for target,content in [(archive,raw),(private_archive,session_raw)]:
   target.parent.mkdir(parents=True,exist_ok=True)
   with target.open('xb') as stream:stream.write(content)
  work.mkdir(parents=True,exist_ok=True)
  with (work/'attempt.json').open('x',encoding='utf8') as stream:json.dump(dict(game_id=gid,authorized_FUN_exploration=True,max_additional_attempts=max_additional_attempts,max_gross_debit_native=max_debit_native,started_at=now()),stream)
  started=True;state.update(active_game=gid,updated_at=now());save(ROOT/'run-state.json',state);sequence=0;reserved=False
  with VariantGate(ROOT,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
   def checkpoint(stage,payload):
    nonlocal sequence,result,reserved
    if stage=='source_verified' and not reserved:
     state.update(last_launch_epoch=gate.reserve(),active_game=gid,updated_at=now());save(ROOT/'run-state.json',state);reserved=True
    sequence+=1;result=copy.deepcopy(payload['report']);save(work/f'checkpoint-{sequence:05d}.json',dict(stage=stage,payload=payload,time=now()))
    native_snapshot(stage);save(path,result)
   def fetch(url):
    gate.check()
    with demo.opener.open(urllib.request.Request(official_url(url),headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
     official_url(response.url);return response.read()
   try:result=explore(demo,original,authorized=True,max_additional_attempts=max_additional_attempts,max_debit_native=max_debit_native,mode_names=mode_names,gate=gate,checkpoint=checkpoint,fetch_source=fetch)
   except Exception as error:
    result=result or copy.deepcopy(original);result.update(status='needs_review',isolated_error_type=type(error).__name__,events=demo.events,checks=demo.money_checks)
  result['finished_at']=now();save(path,result)
  print(gid,result['status'],'additional_attempts',result.get('conditional_exploration',{}).get('additional_attempts',0),'gross_native_debit',result.get('conditional_exploration',{}).get('gross_debit_native',0),flush=True)
  return result
 finally:
  try:
   if started:
    result=result or dict(original,status='needs_review');save(path,result)
    state.setdefault('results',{})[gid]=dict(status=result['status'],modes_closed=sum(m.get('status')=='closed' for m in result.get('modes',[])),report=f'live/{gid}.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
  finally:lock.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Bounded extra own-FUN attempts only for existing source-proved needs_trigger modes.')
 parser.add_argument('game_id');parser.add_argument('--authorize-fun-exploration',action='store_true',required=True);parser.add_argument('--max-additional-attempts',type=int,default=20);parser.add_argument('--max-debit-native',type=int,required=True);parser.add_argument('--mode',action='append',dest='mode_names')
 args=parser.parse_args();run(args.game_id,authorized=args.authorize_fun_exploration,max_additional_attempts=args.max_additional_attempts,max_debit_native=args.max_debit_native,mode_names=args.mode_names)
