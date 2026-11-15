"""Parent-only received ChickenFire bonus continuation; no purchase replay."""
import copy,hashlib,http.cookiejar,json,urllib.request
from pathlib import Path
from urllib.parse import urlsplit,quote
from four_modern_slots import load_metadata,plan,run as run_mode,audit,finish_chicken_received,money,PROTOCOL
from resume_oga_combined import public_events
from run_demo_qa import ROOT,PRIVATE,Demo,save,now
from hyperhive_adapter import Hyperhive
from checkpoint_guard import acquire,require_inactive
from all_lucky_variants import VariantGate
GID='ChickenFire'

def validate(report,data,meta):
 modes=plan(data['initial'],meta);events=data.get('events',[])
 if report.get('game',{}).get('game_id')!=GID or report.get('status')!='needs_review' or report.get('protocol')!=PROTOCOL or report.get('declared_modes')!=modes or len(modes)!=5 or len(report.get('modes',[]))!=2 or any(m.get('status')!='closed' or m.get('mode')!=modes[i] for i,m in enumerate(report['modes'])):raise ValueError('Expected two verified native modes and one received paid bonus')
 if data.get('fresh_demo') is not True or data.get('game_id')!=GID or data.get('status')!='received' or len(events)!=4 or public_events(events)!=report.get('events') or any(e.get('status')!=200 for e in events) or any(c.get('ok') is False for c in report.get('checks',[])):raise ValueError('Own exact received context/evidence required')
 if data.get('last_result')!=events[-1]['response']['result'] or data.get('last_response')!=events[-1]['response'] or data.get('last_request')!=events[-1]['request'] or events[-1]['request'].get('method')!='play' or events[-1]['request'].get('params',{}).get('req')!=modes[2]['req'] or data['last_result'].get('final') is not False:raise ValueError('Already received native buy_bonus receipt differs')
 if report.get('protocol_metadata',{}).get('source_sha256')!=meta['source_sha256'] or data.get('metadata',{}).get('source_sha256')!=meta['source_sha256']:raise ValueError('Fresh original source identity differs')
 before=events[-2]['response']['result']['balance'];opening=data['last_result']
 if money(before)-modes[2]['cost_native']!=money(opening['balance']) or opening['resp'].get('baseBet')!=modes[2]['bet_native'] or opening['resp'].get('purchasedFeature')!='buy_bonus' or opening['resp'].get('stageIndex')!=0:raise ValueError('Original native debit/stage/feature differs')
 checks,rounds=audit(data['initial'],events[:-1],meta)
 if not checks or any(c['ok'] is False for c in checks) or len(rounds)!=2 or not all(r['closed'] for r in rounds):raise ValueError('Original two rounds do not independently reconcile')
 return modes,before

def execute(h,report,data,meta,*,gate,persist):
 modes,before=validate(report,data,meta);h.metadata=copy.deepcopy(meta);h.parent.protocol_metadata=h.metadata;h.parent.protocol=PROTOCOL
 report['received_chicken_bonus_recovery']=dict(original_reason=report.get('reason'),original_protocol_metadata=copy.deepcopy(report['protocol_metadata']),received_paid_event=3,no_purchase_replay=True,remaining_new_mode_names=[m['name'] for m in modes[3:]],status='started');report.update(status='running',protocol_metadata=h.metadata);report.pop('reason',None);report.pop('error_type',None)
 native_request=h.request
 def publish(stage):
  h.parent.events=public_events(h.raw_events);report.update(events=h.parent.events,checks=h.parent.money_checks);persist(stage,dict(report=copy.deepcopy(report),last_result=copy.deepcopy(h.last),last_response=copy.deepcopy(h.last_response),metadata=copy.deepcopy(h.metadata)))
 def request(method,req=None):
  gate.check()
  if any(c.get('ok') is False for c in h.parent.money_checks):raise ValueError('Failed native check forbids another request')
  report['received_chicken_bonus_recovery']['operation']=dict(method=method,req=copy.deepcopy(req),status='sending')
  publish('before_native_request')
  try:response=native_request(method,req)
  except Exception:
   report['received_chicken_bonus_recovery']['operation']['status']='uncertain_or_rejected';publish('native_request_failed_no_retry');raise
  report['received_chicken_bonus_recovery']['operation']['status']='received_unvalidated'
  publish('native_response_received_before_validation');return response
 h.request=request
 try:
  publish('received_paid_bonus_preserved')
  outcome=finish_chicken_received(h,modes[2],before_native=before,opening=h.last,start_event=3);outcome['recovered_received_paid_bonus']=True;report['modes'].append(outcome);publish('received_bonus_closed')
  for mode in modes[3:]:
   gate.check();publish('before_remaining_source_purchase');outcome=run_mode(h,mode)
   if outcome.get('status')!='closed':raise ValueError('Remaining native mode did not close')
   report['modes'].append(outcome);publish('remaining_source_purchase_closed')
  checks,rounds=audit(h.initial,h.raw_events,h.metadata);report['received_chicken_bonus_recovery']['audit_summary']=dict(failed=sum(c['ok'] is False for c in checks),rounds=len(rounds),closed=sum(r['closed'] for r in rounds))
  if any(c['ok'] is False for c in checks) or len(rounds)!=5 or not all(r['closed'] for r in rounds):raise ValueError('Independent complete native audit failed')
  report['status']='complete_declared_modes';report['received_chicken_bonus_recovery']['status']='closed_all_five_source_modes';report['received_chicken_bonus_recovery']['operation']['status']='received_validated'
 except Exception as error:
  report.update(status='needs_review',error_type=type(error).__name__);report['received_chicken_bonus_recovery']['status']='received_or_uncertain_requires_review'
 finally:
  h.request=native_request;publish('received_bonus_recovery_finished')
 return report

def restore(report,data):
 u=urlsplit(data['endpoint'])
 if u.scheme!='https' or not (u.hostname or '').endswith('.demo.bgaming-network.com') or u.path!='/api' or u.username or u.password or u.query or u.fragment or u.port not in (None,443):raise ValueError('Official own Hyper endpoint required')
 d=Demo(report['game']);d.page=data['endpoint'].rsplit('/api',1)[0]+'/';d.events=report['events'];d.money_checks=report['checks'];d.protocol=PROTOCOL
 jar=next(h.cookiejar for h in d.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in data.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 h=Hyperhive(d,{'play_token':data['token']});h.raw_events=copy.deepcopy(data['events']);h.initial=data['initial'];h.last=data['last_result'];h.last_response=data['last_response'];h.metadata=report['protocol_metadata'];h.status='received';return h

def once(path,raw):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as stream:stream.write(raw)

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('Pinned static source redirected')

def main():
 lock=acquire(ROOT/'runner.lock');started=False;report=None;state=None;work=PRIVATE/'chicken-received-bonus-finish';path=ROOT/'live/ChickenFire.json';private=PRIVATE/'hyperhive/ChickenFire.session.json'
 try:
  state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
  if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Exact CHECKPOINT_MAINTENANCE required')
  archive=ROOT/'live/attempts/ChickenFire.before-received-bonus-finish.json';backup=PRIVATE/'attempts/ChickenFire.before-received-bonus-finish.session.json'
  if archive.exists() or backup.exists() or (work/'attempt.json').exists():raise ValueError('Existing once-only received bonus attempt forbids replay')
  raw=path.read_bytes();private_raw=private.read_bytes();report=json.loads(raw);data=json.loads(private_raw);h=restore(report,data)
  # Archive received evidence before even fresh static inspection.
  once(archive,raw);once(backup,private_raw);once(work/'attempt.json',json.dumps(dict(game_id=GID,operation='received_bonus_then_only_remaining_super_ultra',started_at=now(),original_report_sha256=hashlib.sha256(raw).hexdigest(),original_private_sha256=hashlib.sha256(private_raw).hexdigest())).encode());started=True
  state.update(active_game=GID,updated_at=now());save(ROOT/'run-state.json',state);sequence=0
  with VariantGate(ROOT,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
   def persist(stage,payload):
    nonlocal sequence
    sequence+=1;save(work/f'checkpoint-{sequence:05d}.json',dict(stage=stage,payload=payload,time=now()));save(path,report)
   static=urllib.request.build_opener(NoRedirect());frontend_route='/?token='+quote(h.token,safe='')
   def fetch(route):
    gate.check()
    if route!=frontend_route and route not in __import__('four_modern_slots').PINS[GID]:raise ValueError('Unpinned static route')
    with static.open(urllib.request.Request(h.origin+route,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
     if response.url!=h.origin+route or response.status!=200:raise ValueError('Pinned static route changed')
     content=response.read(5000001)
    if len(content)>5000000:raise ValueError('Static source too large')
    label=hashlib.sha256(route.encode()).hexdigest()[:12];once(work/('fresh-static-'+label+'.bin'),content);save(work/('static-'+label+'.json'),dict(path=route,sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)));return content
   try:
    html=fetch(frontend_route);meta=load_metadata(GID,html,fetch,data['initial']['result']['config']['purchased_features']);validate(report,data,meta);state.update(last_launch_epoch=gate.reserve(),updated_at=now());save(ROOT/'run-state.json',state);execute(h,report,data,meta,gate=gate,persist=persist)
   except Exception as error:report.update(status='needs_review',error_type=type(error).__name__);persist('recovery_failed_no_retry',dict(error_type=type(error).__name__))
  report['finished_at']=now();save(path,report)
 finally:
  try:
   if started:
    save(path,report);state.setdefault('results',{})[GID]=dict(status=report['status'],modes_closed=sum(m.get('status')=='closed' for m in report.get('modes',[])),report='live/ChickenFire.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
  finally:lock.close()
 if report is not None:print(GID,report['status'],'closed',sum(m.get('status')=='closed' for m in report.get('modes',[])),flush=True)

if __name__=='__main__':main()
