"""Isolated parent CLI for the one remaining Lucky Dragon native UI control.

Run manually only after review. Importing this module does not launch anything.
Original public/private evidence is archived once; no old session is restored.
"""
import copy
import hashlib
import json
from pathlib import Path
import urllib.request
from run_demo_qa import ROOT,PRIVATE,Demo,save,now
from checkpoint_guard import acquire,require_inactive
from all_lucky_variants import VariantGate
from finish_lucky_dragon_controls import GID,BASE,VERSION,finish,normalize_received

class _NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('Pinned static source redirected')

def _write_once(path,raw):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as stream:stream.write(raw)

def _snapshot(demo):
 if demo is None:return None
 cookies=[]
 for handler in getattr(getattr(demo,'opener',None),'handlers',[]):
  if isinstance(handler,urllib.request.HTTPCookieProcessor):cookies=[dict(name=c.name,value=c.value,domain=c.domain,path=c.path,secure=c.secure,expires=c.expires) for c in handler.cookiejar]
 return dict(fresh_demo=True,game_id=GID,api=getattr(demo,'api',None),page=getattr(demo,'page',None),csrf_name=getattr(demo,'csrf_name',None),csrf_value=getattr(demo,'csrf_value',None),cookies=cookies,series=getattr(demo,'series',None),last_response=copy.deepcopy(getattr(demo,'last_response',None)),last_request=copy.deepcopy(getattr(demo,'last_request',None)),public_events=copy.deepcopy(getattr(demo,'events',[])),money_checks=copy.deepcopy(getattr(demo,'money_checks',[])),protocol_metadata=copy.deepcopy(getattr(demo,'protocol_metadata',{})))

def _partial_report(original,working,demo):
 result=copy.deepcopy(working if working is not None else original)
 old_events=copy.deepcopy(original['events']);offset=len(old_events)
 fresh=copy.deepcopy(getattr(demo,'events',[])) if demo is not None else []
 result['events']=[dict(event,session_context='historical',event_alias_id=f'historical:{i}') for i,event in enumerate(old_events)]+[dict(event,session_context='fresh_control1',event_alias_id=f'fresh_control1:{i}') for i,event in enumerate(fresh)]
 result['checks']=copy.deepcopy(original.get('checks',[]))+[dict(copy.deepcopy(c),session_context='fresh_control1') for c in getattr(demo,'money_checks',[]) or []]
 result['status']='needs_review';result['reason']='Isolated remaining-control execution requires review; original evidence and all received fresh events/checks are retained privately and in their session namespace.'
 if fresh:
  result['session_contexts']=[dict(id='historical',first_event=0,last_event=offset-1,financial_continuity_verified=False),dict(id='fresh_control1',first_event=offset,last_event=offset+len(fresh)-1,initial_event=offset,continuity_with_previous_context_required=False)]
  initial=fresh[0].get('response',{});balance=initial.get('balance')
  if isinstance(balance,dict):
   result['session_contexts'][1]['native_initial_balance']=copy.deepcopy(balance)
   result['initialization_observations']=[dict(session_context='fresh_control1',event=offset,balance=copy.deepcopy(balance),baseline_authority='actual_fresh_init',not_a_wallet_transfer=True)]
  result['uncompleted_fresh_control_observation']=dict(last_event=len(result['events'])-1,received_state=fresh[-1].get('response',{}).get('flow',{}).get('state'),no_resend=True)
 return result

def run(*,root=ROOT,private=PRIVATE,demo_factory=Demo,finish_fn=finish,fetch_static=None,output=print):
 root=Path(root).resolve();private=Path(private).resolve();lock=acquire(root/'runner.lock');state=None;attempt_started=False;result=None
 holder={'demo':None,'working':None,'source':None,'archived':False,'sequence':0}
 report_path=root/'live'/f'{GID}.json';session_path=private/f'{GID}.session.json'
 public_archive=root/'live/attempts'/f'{GID}.before-finish-ui-controls.json'
 private_archive=private/'attempts'/f'{GID}.before-finish-ui-controls.session.json'
 work=private/'lucky-dragon-finish-controls'
 try:
  state=json.loads((root/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
  if (root/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('CHECKPOINT_MAINTENANCE is required for this isolated parent execution')
  if public_archive.exists() or private_archive.exists() or (work/'attempt.json').exists():raise ValueError('Existing isolated attempt/evidence requires review; no replay')
  report_bytes=report_path.read_bytes();session_bytes=session_path.read_bytes();original=json.loads(report_bytes);old_private=json.loads(session_bytes)
  if original.get('game',{}).get('game_id')!=GID or len(original.get('events',[]))!=4:raise ValueError('Expected four-event historical Lucky Dragon evidence missing')
  if old_private.get('fresh_demo') is not True or old_private.get('game_id')!=GID or old_private.get('operation',{}).get('status')!='received' or old_private.get('public_events')!=original['events']:raise ValueError('Received own-suite private/public historical evidence differs')
  if old_private.get('last_request',{}).get('options')!={'bet':10,'purchased_feature':'bonus_buy_0_chance'} or old_private.get('last_response',{}).get('balance')!=original['events'][-1]['response'].get('balance') or old_private.get('last_response',{}).get('flow',{}).get('state')!='closed':raise ValueError('Historical received private control state differs')
  _write_once(work/'attempt.json',json.dumps(dict(game_id=GID,started_at=now(),source_report_sha256=hashlib.sha256(report_bytes).hexdigest(),operation='remaining_ui_control1_only'),indent=2).encode())
  attempt_started=True;state.update(active_game=GID,updated_at=now());save(root/'run-state.json',state)
  def checkpoint(stage,payload):
   if stage=='historical_context_preserved':
    if holder['archived'] or report_path.read_bytes()!=report_bytes or session_path.read_bytes()!=session_bytes:raise ValueError('Historical context changed before once-only archival')
    _write_once(public_archive,report_bytes);_write_once(private_archive,session_bytes);holder['archived']=True
   holder['sequence']+=1
   item=dict(stage=stage,payload=copy.deepcopy(payload),fresh_private_context=_snapshot(holder['demo']),time=now())
   save(work/f'checkpoint-{holder["sequence"]:03d}.json',item);save(work/'checkpoint.json',item)
   if payload.get('last_launch_epoch') is not None:
    state.update(last_launch_epoch=payload['last_launch_epoch'],active_game=GID,updated_at=now());save(root/'run-state.json',state)
   if stage=='before_independent_official_FUN_launch':
    if not holder['archived']:raise ValueError('Old public/private context must be archived before fresh launch')
    if holder['source'] is not None:
     holder['working']=normalize_received(original,holder['source']);save(report_path,holder['working'])
   if stage=='derived_report_ready':holder['working']=copy.deepcopy(payload['report'])
  static_opener=urllib.request.build_opener(_NoRedirect())
  def fetch(url):
   if url not in (BASE+'loader.js',BASE+VERSION+'/bundle.js'):raise ValueError('Unpinned static source URL')
   if fetch_static is not None:raw=fetch_static(url)
   else:
    with static_opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
     if response.url!=url:raise ValueError('Pinned static source redirected')
     raw=response.read()
   if not isinstance(raw,bytes):raise ValueError('Static source callback must return original bytes')
   if url.endswith('/bundle.js'):holder['source']=raw
   return raw
  def launch():
   if not holder['archived'] or holder['demo'] is not None:raise ValueError('Independent fresh launch is once-only after archival')
   demo=demo_factory(copy.deepcopy(original['game']));holder['demo']=demo
   initial=demo.launch()
   save(work/'fresh-session-after-init.json',_snapshot(demo))
   return demo,initial
  try:
   with VariantGate(root,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
    result=finish_fn(original,gate=gate,fresh_launch=launch,fetch_source=fetch,private_checkpoint=checkpoint,old_private_context=old_private)
  except Exception as error:
   result=_partial_report(original,holder['working'],holder['demo']);result['isolated_error_type']=type(error).__name__
   save(work/'interruption.json',dict(error_type=type(error).__name__,fresh_private_context=_snapshot(holder['demo']),public_report=copy.deepcopy(result),time=now()))
  result['finished_at']=now();save(report_path,result)
  return result['status']
 finally:
  try:
   if attempt_started:
    if result is None:result=_partial_report(original,holder['working'],holder['demo']);result['finished_at']=now();save(report_path,result)
    save(work/'fresh-session-final.json',_snapshot(holder['demo']))
    state.setdefault('results',{})[GID]=dict(status=result['status'],modes_closed=sum(m.get('status')=='closed' for m in result.get('modes',[])),financial_unverified_modes=sum(m.get('financial_verified') is False for m in result.get('modes',[])),report=f'live/{GID}.json')
    state.update(active_game=None,updated_at=now());save(root/'run-state.json',state)
    output(f'{GID} {result["status"]} closed={state["results"][GID]["modes_closed"]} financial_unverified={state["results"][GID]["financial_unverified_modes"]}')
  finally:lock.close()

if __name__=='__main__':run()
