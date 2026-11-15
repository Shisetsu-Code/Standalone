"""Run only untested OGA modes after a recorded final; preserve earlier monetary discrepancies."""
import json,time,http.cookiejar,urllib.request,shutil,sys,copy
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from hyperhive_adapter import Hyperhive
from resume_oga_combined import public_events
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid=sys.argv[1]
 if gid not in ['TheGodfather3PillarsOfPower','RocketEruptionTripleBlast']:raise ValueError('Unprepared remaining mode')
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 path=ROOT/'live'/(gid+'.json');report=json.loads(path.read_text(encoding='utf8'));private=PRIVATE/'hyperhive'/(gid+'.session.json');data=json.loads(private.read_text(encoding='utf8'))
 if not data.get('fresh_demo') or data['game_id']!=gid or data['status']!='received' or data['initial']['result']['currency']!='FUN' or data['last_result'].get('final') is not True:raise RuntimeError('Only received final FUN context may start another mode')
 if public_events(data['events'])!=report['events'] or len(report['modes'])!=2 or report['modes'][-1].get('monetary_status')!='unresolved_native_balance_discontinuity':raise RuntimeError('Prior closure/money review not classified')
 archive=ROOT/'live'/'attempts'/(gid+'.before-last-oga-mode.json')
 backup=PRIVATE/'attempts'/(gid+'.before-last-oga-mode.session.json')
 if archive.exists():
  if report!=json.loads(archive.read_text(encoding='utf8')) or not backup.exists() or data!=json.loads(backup.read_text(encoding='utf8')):raise RuntimeError('Remaining mode may have been attempted; no retry')
  print('Prior local preflight stopped before network; public and private checkpoints unchanged',flush=True)
 else:
  save(archive,copy.deepcopy(report));backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,backup)
 parent=Demo(report['game']);parent.page=data['endpoint'].rsplit('/api',1)[0]+'/hyperhive';parent.events=report['events'];parent.money_checks=report['checks'];jar=next(handler.cookiejar for handler in parent.opener.handlers if isinstance(handler,urllib.request.HTTPCookieProcessor))
 for c in data.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 h=Hyperhive(parent,{'play_token':data['token']});h.raw_events=data['events'];h.initial=data['initial'];h.last=data['last_result'];h.last_response=data['last_response'];h.metadata=data['metadata']
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);report.update(status='running');save(path,report)
 try:
  for mode in report['declared_modes'][len(report['modes']):]:
   report['modes'].append(h.run_mode(mode,h.initial));parent.events=public_events(h.raw_events);report.update(events=parent.events,checks=parent.money_checks);save(path,report)
  report.update(status=completion_status(report,h.metadata),reason='All declared API modes closed; earlier observed native balance discontinuity remains unresolved and failed checks are retained')
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=public_events(h.raw_events),checks=parent.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,report['status'],'closed',state['results'][gid]['modes_closed'])
