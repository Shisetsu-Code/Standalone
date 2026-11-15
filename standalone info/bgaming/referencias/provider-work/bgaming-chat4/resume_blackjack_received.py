"""Finish only the exact received SurrenderMultihandBlackjack surrender, then declared modes.

Importing/validating performs no actions. Explicit CLI execution owns runner lock,
pause/pacing/provenance/source gates and once-only public/private archives. No init,
start, or surrender is replayed for the already-paid current hand.
"""
import copy
import json
import math
from pathlib import Path
import time
import blackjack_extra as blackjack
from checkpoint_guard import require_inactive

GID='SurrenderMultihandBlackjack'
SOURCE_SHA='fe9973c6746e114d9f6062d0134dfa7d71c34d3ff7855796c25fec2958a6f899'
RECEIVED_SHA='5c74c148333eeaaaac13af7727ad525c0c8f50e9a809a6126d77e65787f96fa2'


def guard(state,stop,epoch):
 require_inactive(state)
 if stop.strip()=='CONTINUE':raise RuntimeError('Pause between games before resuming received surrender')
 previous=state.get('last_launch_epoch',0)
 if type(previous) not in (int,float) or not math.isfinite(previous) or previous>epoch:raise ValueError('Invalid/future game pacing timestamp')
 return max(0,60-(epoch-previous))


def validate(demo,report,credentials,proof):
 events=report.get('events',[]);done=report.get('modes',[]);declared=report.get('declared_modes',[])
 if (demo.game.get('game_id')!=GID or report.get('game',{}).get('game_id')!=GID
     or not credentials.get('fresh_demo') or credentials.get('game_id')!=GID
     or credentials.get('operation',{}).get('status')!='received' or credentials.get('series')!=demo.series):
  raise ValueError('Fresh owned received surrender context required')
 if len(events)!=26 or len(done)!=7 or len(declared)<=7:raise ValueError('Only exact reviewed seven-result/received-surrender checkpoint may resume')
 if (not proof.get('blackjack_extra_verified') or proof.get('game_id')!=GID
     or proof.get('source_sha256')!=SOURCE_SHA or report.get('protocol_metadata',{}).get('source_sha256')!=SOURCE_SHA):
  raise ValueError('Fresh source proof differs from received native game source')
 last=demo.last_response;public=events[-1]
 if (demo.clean.clean(copy.deepcopy(credentials.get('last_response')))!=public.get('response')
     or demo.clean.clean(copy.deepcopy(last))!=public.get('response')
     or credentials.get('last_response')!=last):raise ValueError('Private/public received blackjack checkpoint differs; no replay')
 initial=events[0].get('response',{});currency=initial.get('options',{}).get('currency',{})
 if events[0].get('status')!=200 or currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Original accepted native FUN init required')
 native_modes=blackjack.plan(initial,proof)
 if declared!=native_modes:raise ValueError('Declared blackjack plan differs from fresh pinned source/native prices')
 mode=declared[len(done)]
 if (mode.get('name')!='area_1/surrender' or mode.get('target')!='surrender'
     or mode.get('source_sha256')!=SOURCE_SHA
     or public.get('status')!=200 or public.get('response_sha256')!=RECEIVED_SHA
     or public.get('request',{}).get('command')!='surrender'
     or public['request'].get('options')!={'area_name':'area_1'}
     or last.get('game',{}).get('action')!='surrender' or last['game'].get('state')!='finished'
     or last.get('current_area')!='none' or not blackjack.available(last,'finish') or blackjack.available(last,'start')):
  raise ValueError('Exact accepted surrendered area_1 hand awaiting finish required')
 if not any(a.get('name')=='area_1' and a.get('surrended') is True for a in last.get('areas',[])):raise ValueError('Source native surrender flag missing')
 return mode,initial


def execute(demo,report,credentials,proof,*,persist=None):
 """Execution core; parent must hold lock/pause/pacing and once-only archives."""
 mode,initial=validate(demo,report,credentials,proof)
 persist=persist or (lambda:None)
 original_call=demo.call;first_request=True
 demo.protocol='blackjack-extra';demo.protocol_metadata=proof
 report.update(protocol='blackjack-extra',protocol_metadata=proof,status='running')
 def publish():
  report.update(events=demo.events,checks=demo.money_checks)
  persist()
 def observed_call(command,options=None):
  nonlocal first_request
  if first_request and (command!='finish' or options is not None):raise ValueError('First recovery action must finish received hand only')
  report['blackjack_received_recovery_operation']=dict(event=len(demo.events),command=command,status='sending')
  publish()
  try:
   response=original_call(command,options) if options is not None else original_call(command)
  except Exception as error:
   report['blackjack_received_recovery_operation'].update(status='uncertain_or_rejected',error_type=type(error).__name__)
   publish();raise
  first_request=False
  report['blackjack_received_recovery_operation']['status']='received'
  publish();return response
 demo.call=observed_call
 try:
  resumed=blackjack.resume_received(demo,mode,initial)
  if resumed.get('status')!='closed':raise ValueError('Received surrender did not close natively')
  report['modes'].append(resumed)
  report['received_blackjack_recovery_audit']=blackjack.audit(report)
  publish()
  if report['received_blackjack_recovery_audit']['failed']:raise ValueError('Independent native blackjack audit failed; no further paid mode')
  for remaining in report['declared_modes'][len(report['modes']):]:
   result=demo.run_mode(remaining,initial)
   report['modes'].append(result);publish()
   if result.get('status') not in ('closed','needs_trigger','not_applicable'):break
  report['received_blackjack_recovery_audit']=blackjack.audit(report)
  from run_demo_qa import completion_status
  report['status']=completion_status(report,proof)
  if len(report['modes'])!=len(report['declared_modes']):report['status']='partial'
  if report['received_blackjack_recovery_audit']['failed']:report['status']='needs_review'
  if report['status']!='needs_review':report.pop('reason',None);report.pop('error_type',None)
 except Exception as error:
  report.update(status='needs_review',reason=str(error) if isinstance(error,(RuntimeError,ValueError,KeyError)) else type(error).__name__)
 finally:
  demo.call=original_call
  publish()
 return report


def _archive(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x',encoding='utf8') as handle:
  json.dump(value,handle,ensure_ascii=False,indent=2);handle.flush()
  import os
  os.fsync(handle.fileno())


def main():
 from checkpoint_guard import acquire
 from legacy_recovery import restore
 from legacy_metadata import prove_blackjack
 from run_demo_qa import ROOT,PRIVATE,save,now
 lock=acquire(ROOT/'runner.lock')
 state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 delay=guard(state,(ROOT/'STOP').read_text(encoding='utf8'),time.time())
 demo,report=restore(GID)
 credentials=json.loads((PRIVATE/(GID+'.session.json')).read_text(encoding='utf8'))
 # load_client inside prove_blackjack reuses the exact cached loader/bundle; any
 # newly fetched source must still match the reviewed received source hash.
 proof=prove_blackjack(GID,demo.opener)
 delay=guard(state,(ROOT/'STOP').read_text(encoding='utf8'),time.time())
 validate(demo,report,credentials,proof)
 archive=ROOT/'live/attempts'/(GID+'.before-received-surrender-finish.json')
 private_archive=PRIVATE/'attempts'/(GID+'.before-received-surrender-finish.session.json')
 if archive.exists() or private_archive.exists():raise RuntimeError('Received surrender recovery already attempted; no replay')
 _archive(archive,report);_archive(private_archive,credentials)
 time.sleep(delay)
 guard(state,(ROOT/'STOP').read_text(encoding='utf8'),time.time())
 state.update(active_game=GID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 path=ROOT/'live'/(GID+'.json')
 def persist():report.update(events=demo.events,checks=demo.money_checks);save(path,report)
 try:execute(demo,report,credentials,proof,persist=persist)
 finally:
  report['finished_at']=now();persist()
  state['results'][GID]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+GID+'.json')
  state.update(active_game=None,updated_at=now());save(state_path,state);lock.close()
 print(GID,report['status'],'received surrender finish retained;',len(report['modes']),'declared results',flush=True)


if __name__=='__main__':main()
