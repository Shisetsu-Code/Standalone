"""Parent-executed, once-only fresh FUN evidence for 16 manual first-door choices.

Imports and pure helpers do not launch, dispatch, or write checkpoints. Execution
requires --execute, the shared runner lock, an inactive paused queue and pacing.
Old report/session evidence remains unchanged; new aliases and native money are
scoped to a separate fresh context and a new derived report.
"""
import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

import run_demo_qa as runtime
from run_demo_qa import Demo, ROOT, PRIVATE, save, now, modes_from_init
from bonus_choices_extra import PINS, metadata, prepare, check_event

GID='WildMoonThieves'
PIN=PINS[GID]
CONTEXT_ID='manual-doors'


def cached_proof():
 for path in (PRIVATE/'research/legacy'/GID).rglob('bundle.js'):
  raw=path.read_bytes()
  if hashlib.sha256(raw).hexdigest()==PIN:return metadata(GID,raw.decode('utf8'))
 raise ValueError('Pinned Wild Moon source cache is missing; no actions permitted')


def _proof(proof):
 if proof.get('game_id')!=GID or not proof.get('source_verified') or proof.get('source_sha256')!=PIN or proof.get('choices')!=list(range(16)):
  raise ValueError('Pinned sixteen-door source proof required')


def _native(value):
 if type(value) is not int or value<0:raise ValueError('Original nonnegative integer FUN amount required')
 return value


def _balance(response):
 b=response.get('balance',{})
 return _native(b.get('wallet')),_native(b.get('game'))


def _price(initial,request):
 args=request.get('options',{});o=initial['options'];fo=o['feature_options'];fm=fo['feature_multipliers']
 if request.get('command')!='spin' or set(args)!={'bet','purchased_feature'} or args.get('purchased_feature')!='freespin_buy' or 'freespin_buy' in fo.get('disabled_features',[]):raise ValueError('Only the received preselection-trigger purchase is authorized')
 bet=_native(args['bet']);base=_native(fm.get('base_bet'));mult=_native(fm.get('freespin_buy'))
 if not bet or bet not in o['available_bets'] or not base or not mult:raise ValueError('Native minimum/feature price missing')
 cost,remainder=divmod(bet*mult,base)
 if remainder:raise ValueError('Unproved fractional native trigger price')
 return cost


def validate_original(old):
 if old.get('game',{}).get('game_id')!=GID or len(old.get('modes',[]))!=3 or {x.get('mode',{}).get('name') for x in old['modes']}!={'normal','freespin_buy','bonus_buy'} or any(x.get('status')!='closed' for x in old['modes']):
  raise ValueError('Exactly the three already closed original Wild Moon modes are required')
 if not old.get('events') or old['events'][-1].get('response',{}).get('flow',{}).get('state')!='closed':raise ValueError('Original owned round is not closed; never abandon or rebuy it')
 if old.get('protocol_metadata',{}).get('continuation_source',{}).get('source_sha256')!=PIN:raise ValueError('Original client source does not match manual pin')
 if any(c.get('ok') is False for c in old.get('checks',[])):raise ValueError('Original monetary discrepancy cannot be hidden by a new context')


def select_trigger(old,fresh_initial):
 validate_original(old)
 features=set()
 for mode in old['modes']:
  index=mode.get('first_event')
  if type(index) is not int or not 0<=index<len(old['events']):continue
  event=old['events'][index];q=event.get('request',{});r=event.get('response',{});feature=q.get('options',{}).get('purchased_feature')
  if (event.get('status')==200 and q.get('command')=='spin' and feature
      and r.get('flow',{}).get('state')=='preselection_game'
      and 'play_preselection_game' in r['flow'].get('available_actions',[])
      and r['flow'].get('purchased_feature',{}).get('name')==feature):features.add(feature)
 if features!={'freespin_buy'}:raise ValueError('No unique received native purchase proves entry into preselection')
 candidates=[m for m in modes_from_init(fresh_initial) if m.get('options',{}).get('purchased_feature')=='freespin_buy']
 if len(candidates)!=1:raise ValueError('Fresh native purchase menu differs from received trigger')
 mode=copy.deepcopy(candidates[0]);cost=_price(fresh_initial,{'command':mode['command'],'options':mode['options']})
 if mode['cost_native']!=cost:raise ValueError('Runtime trigger cost differs from independent native menu price')
 return mode


def manual_modes(old,initial,proof):
 _proof(proof);mode=select_trigger(old,initial);result=[]
 for index in range(16):
  item=copy.deepcopy(mode);item.update(name='manual_first_door:'+str(index)+'/freespin_buy',manual_initial_door=index)
  result.append(item)
 return result


def play_manual_doors(demo,response,proof,target):
 _proof(proof)
 if type(target) is not int or not 0<=target<16:raise ValueError('Manual initial door must be 0..15')
 first=True
 for _ in range(16):
  if response.get('flow',{}).get('state')!='preselection_game':
   if first:raise ValueError('Received purchase did not enter manual preselection; no replacement purchase')
   return response
  history=response.get('features',{}).get('preselection_game',{}).get('doors',[])
  opened=[d.get('index') for d in history]
  choice=target if first else next((i for i in range(16) if i not in opened),None)
  request=prepare(response,proof,choice);before=response;event_index=len(demo.events)
  response=demo.call(request['command'],request['options'])
  checked=check_event(before,dict(request=request,response=response,status=200),proof)
  demo.money_checks.append(dict(event=event_index,**checked))
  evidence=dict(event=event_index,command=request['command'],options=request['options'],manual_first=first,manual_initial_door=target)
  demo.choice_actions=getattr(demo,'choice_actions',[])+[evidence]
  demo.manual_door_actions=getattr(demo,'manual_door_actions',[])+[evidence]
  first=False
  if response.get('features',{}).get('preselection_game',{}).get('finished') is True:return response
 raise ValueError('Sixteen distinct manual doors did not finish source preselection')


class ManualWildMoonDemo(Demo):
 # Keep the existing paid run_mode debit and native feature receipt validation.
 # Only settlement changes: manual doors first, then the existing bonus engine.
 def settle(self,response):
  proof=self.manual_proof;target=self.active_mode.get('manual_initial_door')
  response=play_manual_doors(self,response,proof,target)
  if response.get('flow',{}).get('state') not in ('freespins','respin','closed'):raise ValueError('Manual doors did not transition into the source bonus')
  original_call=self.call;had_own='call' in self.__dict__;own_call=self.__dict__.get('call')
  def guarded_call(command,options=None):
   if command not in ('freespin','respin') or options is not None:raise RuntimeError('Unexpected bonus action blocked before dispatch; no automatic door or extra purchase')
   return original_call(command)
  self.call=guarded_call
  try:return Demo.settle(self,response)
  finally:
   if had_own:self.call=own_call
   else:del self.call


def audit_manual_context(context,proof):
 """Independent native price, wallet, action identity and manual history audit."""
 _proof(proof);events=context.get('events',[]);checks=[];starts={};verified=set();first_indices=[];all_indices=[];paid=closed=cost_total=0;active=None
 if not events:
  checks.append(dict(kind='manual_native_init',ok=False,reason='No accepted fresh init received'))
 else:
  first=events[0];initial=first.get('response',{});o=initial.get('options',{});c=o.get('currency',{})
  if first.get('status')!=200 or first.get('request',{}).get('command')!='init' or c.get('code')!='FUN' or c.get('subunits')!=100:
   checks.append(dict(event=0,kind='manual_native_init',ok=False,reason='Original native fresh FUN init required'))
  else:
   try:expected_wallet,expected_game=_balance(initial)
   except ValueError as error:checks.append(dict(event=0,kind='manual_native_init',ok=False,reason=str(error)))
   else:
    checks.append(dict(event=0,kind='manual_native_init',ok=True));previous=initial;seen_rounds=set()
    for index,event in enumerate(events[1:],1):
     q=event.get('request',{});r=event.get('response',{});command=q.get('command')
     try:
      if event.get('status')!=200 or r.get('errors'):raise ValueError('Unaccepted/uncertain action is not coverage')
      old_flow=previous.get('flow',{});flow=r.get('flow',{});wallet,game=_balance(r)
      if command not in old_flow.get('available_actions',[]):raise ValueError('Native action was not advertised')
      if not flow.get('last_action_id') or flow.get('last_action_id')==old_flow.get('last_action_id') or flow.get('command')!=command:raise ValueError('Native action identity/command mismatch')
      if command=='spin':
       if active is not None or old_flow.get('state') not in ('closed','ready') or old_flow.get('state')=='ready' and expected_game:raise ValueError('New purchase before prior native round closed')
       cost=_price(initial,q);paid+=1;cost_total+=cost;rid=flow.get('round_id')
       if not rid or rid in seen_rounds or flow.get('state')!='preselection_game' or flow.get('purchased_feature',{}).get('name')!='freespin_buy':raise ValueError('Native purchase did not confirm unique preselection parent')
       if r.get('outcome',{}).get('bet')!=q['options']['bet']:raise ValueError('Native base wager receipt mismatch')
       seen_rounds.add(rid);expected_wallet+=expected_game-cost;expected_game=_native(r.get('outcome',{}).get('win'))
       active=dict(start=index,first=None,doors_finished=False,round_id=rid,cost=cost);starts[index]=active
       checks.append(dict(event=index,kind='manual_purchase_source_price',cost_native=cost,ok=True))
      elif command=='play_preselection_game':
       if active is None:raise ValueError('Door action has no received purchase')
       checked=check_event(previous,event,proof);choice=q.get('options',{}).get('index')
       if active['first'] is None:active['first']=choice;first_indices.append(choice)
       all_indices.append(choice);active['doors_finished']=checked['preselection_finished'];checks.append(dict(event=index,**checked))
      elif command in ('freespin','respin'):
       if active is None or not active['doors_finished'] or q.get('options') is not None or flow.get('round_id')!=active['round_id']:raise ValueError('Unproved free bonus transition after manual doors')
       expected_game+=_native(r.get('outcome',{}).get('win'))
      else:raise ValueError('Unreviewed action or mid-context init reset')
      if (wallet,game)!=(expected_wallet,expected_game):raise ValueError('Original native wallet/game conservation mismatch')
      checks.append(dict(event=index,kind='manual_expected_native_balance',expected_native={'wallet':expected_wallet,'game':expected_game},actual_native=r['balance'],ok=True));verified.add(index)
      if active is not None and flow.get('state')=='closed':
       active['end']=index;closed+=1;active=None
      previous=r
     except (ValueError,KeyError,TypeError,AttributeError) as error:
      checks.append(dict(event=index,kind='manual_source_native_audit',ok=False,reason=str(error)));break
 valid_modes=0;mode_starts=set()
 for item in context.get('modes',[]):
  if item.get('status')!='closed':continue
  start=item.get('first_event');end=item.get('last_event');mode=item.get('mode',{});receipt=starts.get(start,{})
  ok=(type(start) is int and type(end) is int and start not in mode_starts and end in verified and receipt.get('end')==end
      and receipt.get('first')==mode.get('manual_initial_door') and mode.get('cost_native')==receipt.get('cost')
      and events[start]['request'].get('options')==mode.get('options'))
  checks.append(dict(event=end,kind='manual_initial_target_receipt',ok=bool(ok)))
  if ok:valid_modes+=1;mode_starts.add(start)
 failed=sum(c.get('ok') is not True for c in checks);seen=sorted(set(first_indices));pending=[i for i in range(16) if i not in seen]
 return dict(game_id=GID,events=len(events),checks=checks,passed=sum(c.get('ok') is True for c in checks),failed=failed,
             paid_attempts=paid,rounds_closed=closed,cost_native=cost_total,first_indices_executed=seen,
             manual_indices_executed=sorted(set(all_indices)),pending_initial_indices=pending,
             complete=not failed and paid==closed==valid_modes==16 and len(first_indices)==16 and not pending)


def derive_report(old,manual,proof):
 validate_original(old);audit=audit_manual_context(manual,proof)
 modes=[dict(copy.deepcopy(m),context_id='original') for m in old['modes']]+[dict(copy.deepcopy(m),context_id=CONTEXT_ID) for m in manual.get('modes',[])]
 declared=[dict(copy.deepcopy(m),context_id='original') for m in old.get('declared_modes',[])]+[dict(copy.deepcopy(m),context_id=CONTEXT_ID) for m in manual.get('declared_modes',[])]
 return dict(game=copy.deepcopy(old['game']),protocol='wild-moon-manual-contexts',
             status='complete_declared_modes' if audit['complete'] else 'partial',modes=modes,declared_modes=declared,
             contexts=[dict(context_id='original',report=copy.deepcopy(old)),dict(context_id=CONTEXT_ID,report=copy.deepcopy(manual))],
             protocol_metadata=dict(manual_door_source=copy.deepcopy(proof),context_scoped_events=True),
             manual_door_coverage=audit,original_three_modes_preserved=True,
             note='Each context retains its own aliases and actual fresh FUN baseline. No cross-context wallet equality or fabricated prize is asserted.')


def write_once(path,raw):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())


def output_paths(root=ROOT):
 root=Path(root)
 return root/'live/bonus-contexts/WildMoonThieves.manual-doors.context.json',root/'live/WildMoonThieves.json'


@contextmanager
def _private_scope(directory):
 # Process-local redirection only; existing session credentials are never replaced.
 original=runtime.PRIVATE;runtime.PRIVATE=Path(directory)
 try:yield
 finally:runtime.PRIVATE=original


def verify_fresh_source(demo,directory):
 """Parent-only static GETs: validate current loader route and pinned client bytes."""
 from legacy_metadata import client_route
 origin='https://cdn.bgaming-network.com/html/'+GID+'/'
 def fetch(url):
  with demo.opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
   if response.url!=url:raise ValueError('Unexpected official static source redirect')
   return response.read()
 loader=fetch(origin+'loader.js');version,route=client_route(loader.decode('utf8'))
 if '..' in Path(route).parts or not route.endswith('/bundle.js'):raise ValueError('Unreviewed client source route')
 source=fetch(origin+route);proof=metadata(GID,source.decode('utf8'))
 write_once(Path(directory)/'source/loader.js',loader);write_once(Path(directory)/'source/bundle.js',source)
 proof.update(client_version=version,source_url=origin+route,loader_sha256=hashlib.sha256(loader).hexdigest())
 return proof


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true',required=True);parser.parse_args()
 from checkpoint_guard import acquire,require_inactive
 from legacy_recovery import restore
 lock=acquire(ROOT/'runner.lock')
 state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'));require_inactive(state)
 stop_path=ROOT/'STOP';stop_value=stop_path.read_text(encoding='utf8').strip()
 if stop_value=='CONTINUE':raise RuntimeError('Pause the shared queue before this isolated fresh-context run')
 private_context=PRIVATE/'manual-wild-moon-thieves'
 public_context,derived_path=output_paths()
 if private_context.exists() or public_context.exists():raise RuntimeError('Once-only manual context already exists; review its received checkpoint instead of replaying')
 old_demo,old=restore(GID);validate_original(old);proof=cached_proof()
 if old_demo.last_response.get('flow',{}).get('state')!='closed':raise ValueError('Original private native round remains open')
 private_context.mkdir(parents=True,exist_ok=False)
 write_once(private_context/'original.session.json',(PRIVATE/(GID+'.session.json')).read_bytes())
 write_once(private_context/'run-state.before.json',state_path.read_bytes())
 write_once(ROOT/'live/attempts/WildMoonThieves.before-manual-doors.json',(ROOT/'live'/(GID+'.json')).read_bytes())
 while time.time()-state.get('last_launch_epoch',0)<60:
  if stop_path.read_text(encoding='utf8').strip()!=stop_value:raise RuntimeError('Stop gate changed before fresh launch')
  time.sleep(min(1,60-(time.time()-state.get('last_launch_epoch',0))))
 if stop_path.read_text(encoding='utf8').strip()!=stop_value:raise RuntimeError('Stop gate changed before fresh launch')
 state.update(active_game=GID,active_context_id=CONTEXT_ID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 demo=ManualWildMoonDemo(old['game']);manual=dict(game=copy.deepcopy(old['game']),context_id=CONTEXT_ID,status='starting',started_at=now(),modes=[],events=[],checks=[])
 def persist():
  manual.update(events=copy.deepcopy(demo.events),checks=copy.deepcopy(demo.money_checks),manual_actions=copy.deepcopy(getattr(demo,'manual_door_actions',[])))
  save(public_context,manual);save(derived_path,derive_report(old,manual,proof))
 try:
  with _private_scope(private_context):
   initial=demo.launch();c=initial.get('options',{}).get('currency',{});wallet,game=_balance(initial)
   if c.get('code')!='FUN' or c.get('subunits')!=100 or game or initial.get('flow',{}).get('state') not in ('ready','closed') or 'spin' not in initial['flow'].get('available_actions',[]):raise ValueError('New context must begin at a fresh native FUN init baseline')
   proof=verify_fresh_source(demo,private_context);demo.manual_proof=proof
   demo.protocol_metadata.update(legacy_continuations=['play_preselection_game'],continuation_options={},manual_door_source=proof)
   modes=manual_modes(old,initial,proof)
   if wallet<sum(m['cost_native'] for m in modes):raise ValueError('Fresh native FUN cannot fund the fixed sixteen-purchase budget')
   manual.update(status='running',protocol='legacy',bootstrap=copy.deepcopy(demo.bootstrap),protocol_metadata=copy.deepcopy(demo.protocol_metadata),declared_modes=modes,gross_native_budget=sum(m['cost_native'] for m in modes))
   demo.prev=initial;persist()
   for mode in modes:
    if stop_path.read_text(encoding='utf8').strip()!=stop_value:raise RuntimeError('Stop gate changed; no next purchase sent')
    result=demo.run_mode(mode,initial);manual['modes'].append(result);persist()
    audit=audit_manual_context(manual,proof)
    if result.get('status')!='closed' or audit['failed']:raise RuntimeError('Received manual purchase/door/bonus audit failed; no repeat or next purchase')
   manual['status']='complete_declared_modes' if audit_manual_context(manual,proof)['complete'] else 'partial'
 except Exception as error:
  manual.update(status='needs_review',error_type=type(error).__name__,reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else 'Launch/static/transport failure; no retry')
 finally:
  manual['finished_at']=now();persist();derived=derive_report(old,manual,proof)
  state['results'][GID]=dict(status=derived['status'],modes_closed=sum(m.get('status')=='closed' for m in derived['modes']),report=str(derived_path.relative_to(ROOT)).replace('\\','/'))
  state.update(active_game=None,updated_at=now());state.pop('active_context_id',None);save(state_path,state)
  print(GID,derived['status'],'manual first indices',len(derived['manual_door_coverage']['first_indices_executed']))


if __name__=='__main__':main()
