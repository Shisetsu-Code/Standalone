"""Classify exact received Yommi normal outcome offline; continue only three unplayed buys.

Owned Hyperhive context and native receipts are restored without init/new sessions.
Both server identifiers are absent in this received transport; correlation is limited
to sequential RPC IDs/state_lock and source final/cost/cumulative winnings evidence.
"""
import copy
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import final_rpc_pair as pair

GID='YommiRush'
RECEIVED_SHA='894663c0d05d1ba9cb459cb51e735893907ffb9913ce5184f5ad86320b730148'


def validate(report,data,proof):
 from resume_oga_combined import public_events
 events=report.get('events',[])
 if (report.get('game',{}).get('game_id')!=GID or not data.get('fresh_demo') or data.get('game_id')!=GID
     or data.get('status')!='received' or len(events)!=2 or report.get('modes') or len(data.get('events',[]))!=2):
  raise ValueError('Only exact received owned two-event Yommi normal checkpoint may resume')
 if (public_events(data['events'])!=events or data.get('last_result')!=data['events'][-1]['response'].get('result')
     or data.get('last_response')!=data['events'][-1]['response'] or data.get('last_request')!=data['events'][-1]['request']
     or data.get('initial')!=data['events'][0]['response']):raise ValueError('Owned native/public RPC checkpoints differ; no replay')
 if proof.get('game_id')!=GID or proof.get('source_sha256')!=pair.PINS[GID] or report.get('protocol_metadata',{}).get('source_sha256')!=pair.PINS[GID]:raise ValueError('Received source proof differs from pinned Yommi client')
 initial=events[0]['response'];modes=pair.plan(initial,proof)
 if report.get('declared_modes')!=modes or len(modes)!=4:raise ValueError('Received native Yommi four-mode plan differs')
 event=events[1];result=event['response']['result'];req=event['request'].get('params',{}).get('req')
 if event.get('status')!=200 or event.get('response_sha256')!=RECEIVED_SHA or req!=pair.request(initial,modes[0],proof,initial['result'],first=True):raise ValueError('Exact already-played normal request/receipt required')
 if pair.identifier_policy(result)!='both_absent' or pair.identifier_policy(data['last_result'])!='both_absent':raise ValueError('Recovery only covers both absent server round/step identifiers')
 pair._rpc_correlation(data['events'][-1])
 checked=pair.inspect(result,modes[0],proof,first=True,total_before=0)
 expected=pair._integer(initial['result']['balance'])-20+checked['win_native']
 if not checked['closed'] or checked['cost_native']!=20 or checked['win_native']!=0 or checked['balance_native']!=99980 or expected!=99980:raise ValueError('Received normal native final/cost/win/balance differs')
 checks,rounds=pair.audit(initial,events,proof)
 if len(rounds)!=1 or not checks or any(not c['ok'] for c in checks):raise ValueError('Received normal independent native audit failed')
 return modes,checks,rounds[0]


def classify_received(report,data,proof):
 if report.get('received_yommi_normal_classified'):raise ValueError('Received normal already classified; never replay')
 modes,checks,round_info=validate(report,data,proof)
 proof['received_identifier_policy']='both_absent'
 check=dict(checks[-1],normalized_existing_received_response=True,normalized_received_event=1)
 report.setdefault('checks',[]).append(check)
 report['modes'].append(dict(mode=modes[0],status='closed',first_event=1,last_event=1,final_balance=99980,
   final_state='source_final',win_native=0,network_calls=0,normalized_existing_received_response=True,
   identifier_policy='both_absent',identifier_limitation=round_info['identifier_limitation']))
 report.update(received_yommi_normal_classified=True,protocol='jsonrpc-final-pair',protocol_metadata=proof,status='partial')
 report['identifier_limitation']='Server round/step absent. No invented IDs; only owned sequential RPC/state_lock and source final/cumulative/native balance constraints.'
 return report


def execute(hyper,report,data,proof,*,persist=None):
 validate(report,data,proof)
 persist=persist or (lambda:None)
 classify_received(report,data,proof)
 hyper.metadata=proof
 if hyper.last!=data['last_result'] or hyper.initial!=data['initial']:raise ValueError('Restored Hyperhive state differs from owned checkpoint')
 hyper.parent.events=report['events'];hyper.parent.money_checks=report['checks']
 original_request=hyper.request;first=True
 def publish():report.update(events=hyper.parent.events,checks=hyper.parent.money_checks);persist()
 def observed(method,req=None):
  nonlocal first
  if method!='play' or (first and (req or {}).get('purchased_feature')!='buy_chance'):raise ValueError('Recovery never replays init/normal or an unplanned first purchase')
  report['yommi_recovery_operation']=dict(method=method,event=len(hyper.parent.events),status='sending');publish()
  try:outer=original_request(method,req)
  except Exception as error:
   report['yommi_recovery_operation'].update(status='uncertain_or_rejected',error_type=type(error).__name__);publish();raise
  first=False;report['yommi_recovery_operation']['status']='received';publish();return outer
 hyper.request=observed
 publish()
 try:
  for mode in report['declared_modes'][1:]:
   result=pair.run(hyper,mode);report['modes'].append(result);publish()
   if result['status']!='closed':break
  report['received_yommi_recovery_audit']=pair.audit_report(report)
  from run_demo_qa import completion_status
  report['status']=completion_status(report,proof)
  if len(report['modes'])!=4:report['status']='partial'
  if report['received_yommi_recovery_audit']['failed']:report['status']='needs_review'
  if report['status']!='needs_review':report.pop('reason',None);report.pop('error_type',None)
 except Exception as error:
  report.update(status='needs_review',reason=str(error) if isinstance(error,(RuntimeError,ValueError,KeyError)) else type(error).__name__)
 finally:hyper.request=original_request;publish()
 return report


def restore_context(report,data):
 import http.cookiejar
 import urllib.request
 from run_demo_qa import Demo
 from hyperhive_adapter import Hyperhive
 endpoint=urlsplit(data['endpoint'])
 if endpoint.scheme!='https' or not (endpoint.hostname or '').endswith('.demo.bgaming-network.com') or endpoint.username or endpoint.password or endpoint.path!='/api' or endpoint.query or endpoint.fragment or endpoint.port not in (None,443):raise ValueError('Owned official Hyperhive endpoint required')
 parent=Demo(report['game']);parent.page=data['endpoint'].rsplit('/api',1)[0]+'/hyperhive';parent.events=report['events'];parent.money_checks=report['checks'];parent.protocol='jsonrpc-final-pair'
 jar=next(h.cookiejar for h in parent.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in data.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 h=Hyperhive(parent,{'play_token':data['token']});h.raw_events=data['events'];h.initial=data['initial'];h.last=data['last_result'];h.last_response=data['last_response'];h.metadata=report['protocol_metadata'];h.status=data['status']
 return h


def main():
 from checkpoint_guard import acquire
 from run_demo_qa import ROOT,PRIVATE,save,now
 from resume_dig_choices import require_paused,pacing_delay,_archive_once
 lock=acquire(ROOT/'runner.lock');state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'));require_paused(state,(ROOT/'STOP').read_text(encoding='utf8'))
 path=ROOT/'live'/(GID+'.json');report=json.loads(path.read_text(encoding='utf8'));private=PRIVATE/'hyperhive'/(GID+'.session.json');data=json.loads(private.read_text(encoding='utf8'))
 sources=list((PRIVATE/'research/frontends'/GID).glob('*main.*.js'))
 if len(sources)!=1:raise ValueError('One exact already-cached Yommi main bundle required')
 proof=pair.metadata(GID,sources[0].read_text(encoding='utf8'),data['initial']['result']['config']['purchased_features']);proof['entry_path']=report['protocol_metadata'].get('entry_path')
 validate(report,data,proof)
 archive=ROOT/'live/attempts'/(GID+'.before-received-yommi-normal.json');backup=PRIVATE/'attempts'/(GID+'.before-received-yommi-normal.session.json')
 if archive.exists() or backup.exists():raise RuntimeError('Received Yommi normal recovery already attempted; never replay')
 h=restore_context(report,data)
 _archive_once(archive,report);_archive_once(backup,data)
 time.sleep(pacing_delay(state,time.time()));require_paused(state,(ROOT/'STOP').read_text(encoding='utf8'))
 state.update(active_game=GID,last_launch_epoch=time.time(),updated_at=now());save(state_path,state)
 def persist():save(path,report)
 try:execute(h,report,data,proof,persist=persist)
 finally:
  report['finished_at']=now();persist();state['results'][GID]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+GID+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);lock.close()
 print(GID,report['status'],'closed',sum(m['status']=='closed' for m in report['modes']),flush=True)


if __name__=='__main__':main()
