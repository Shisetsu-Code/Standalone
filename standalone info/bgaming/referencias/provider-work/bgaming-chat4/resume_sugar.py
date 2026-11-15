"""Resume fresh Sugar Plinko after a received closed response; never repeat play."""
import json,time,http.cookiejar,urllib.request
from pathlib import Path
from run_demo_qa import Demo,ROOT,PRIVATE,OUT,save,now,trusted
if __name__=='__main__':
 gid='SugarPlinko';report_path=OUT/(gid+'.json');report=json.loads(report_path.read_text(encoding='utf8'));credentials=json.loads((PRIVATE/(gid+'.session.json')).read_text(encoding='utf8'));state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'))
 assert credentials['fresh_demo'] and credentials['game_id']==gid
 assert credentials['operation']['status']=='received'
 assert report['events'][0]['response']['options']['currency']['code']=='FUN'
 last=credentials['last_response'];assert last['game']['state'] in ('closed','idle')
 from run_demo_qa import modes_from_init
 report['declared_modes']=modes_from_init(report['events'][0]['response'])
 delay=max(0,60-(time.time()-state['last_launch_epoch']))
 if delay:time.sleep(delay)
 state['last_launch_epoch']=time.time();state['active_game']=gid;state.pop('queue_pass_finished_at',None);state['updated_at']=now();save(ROOT/'run-state.json',state)
 demo=Demo(report['game']);demo.api=trusted(credentials['api']);demo.page=credentials['page'];demo.csrf_name=credentials['csrf_name'];demo.csrf_value=credentials['csrf_value'];demo.series=credentials['series'];demo.last_response=last;demo.prev=last;demo.events=report['events'];demo.money_checks=report['checks']
 jar=next(x.cookiejar for x in demo.opener.handlers if isinstance(x,urllib.request.HTTPCookieProcessor))
 for c in credentials['cookies']:
  jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 # Reclassify the already received response using all child outcomes; no network call.
 index=len(report['modes']);mode=report['declared_modes'][index];event=report['events'][-1]
 assert event['request']['command']=='play' and event['request']['options']==mode['options'] and last['game']['state']=='closed'
 components=[x[0] for x in last['game']['outcome']];win=sum(components);before=report['events'][-2]['response']['balance'];expected=before-mode['cost_native']+win
 assert last['balance']==expected
 for check in demo.money_checks:
  if not check['ok']:check['superseded']=True;check['resolution']='Use sum of all native child outcomes, including respins, instead of final outcome only.'
 demo.money_checks.append(dict(expected=expected,actual=last['balance'],ok=True,recovered_received_response=True))
 report.setdefault('resolved_audit_findings',[]).append(dict(event=len(report['events'])-1,reason='Multiple child wins in one response; sum required',win_components_native=components,total_win_native=win))
 report['modes'].append(dict(mode=mode,status='closed',first_event=len(report['events'])-1,last_event=len(report['events'])-1,final_balance=last['balance'],final_state='closed',win_native=win,win_components_native=components,outcome_count=len(components),recovered_received_response=True))
 report['status']='running';report.pop('reason',None);report.pop('error_type',None);save(report_path,report)
 try:
  done={x['mode']['name'] for x in report['modes'] if x['status']=='closed'}
  init=report['events'][0]['response']
  for mode in report['declared_modes']:
   if mode['name'] in done:continue
   report['modes'].append(demo.run_mode(mode,init));report['events']=demo.events;report['checks']=demo.money_checks;save(report_path,report)
  report['status']='complete_declared_modes' if all(x['status']=='closed' for x in report['modes']) else 'partial'
 except Exception as e:report['status']='needs_review';report['reason']=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__
 report['events']=demo.events;report['checks']=demo.money_checks;report['finished_at']=now();save(report_path,report)
 state['results'][gid]=dict(status=report['status'],modes_closed=sum(x['status']=='closed' for x in report['modes']),report='live/'+gid+'.json');state['active_game']=None;state['updated_at']=now();save(ROOT/'run-state.json',state)
 print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],flush=True)
