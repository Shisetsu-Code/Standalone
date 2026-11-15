"""Resume fresh Frenzy mystery purchase, then test each verified portal in a new round."""
import json,time,re,copy,http.cookiejar,urllib.request
from run_demo_qa import Demo,ROOT,PRIVATE,OUT,save,now,trusted

def restore_aliases(clean,events,raw,series):
 maxima={}
 def scan(v):
  if isinstance(v,dict):
   for x in v.values():scan(x)
  elif isinstance(v,list):
   for x in v:scan(x)
  elif isinstance(v,str):
   m=re.fullmatch(r'(round_id|last_action_id|round_series_id)-(\d+)',v)
   if m:maxima[m[1]]=max(maxima.get(m[1],0),int(m[2]))
 scan(events)
 for key,count in maxima.items():
  for i in range(1,count+1):clean.alias[(key,'placeholder-'+str(i))]=key+'-'+str(i)
 def bind(key,value,alias):
  match=re.fullmatch(re.escape(key)+r'-(\d+)',str(alias))
  if match:clean.alias.pop((key,'placeholder-'+match[1]),None);clean.alias[(key,str(value))]=alias
 def align(a,b,key=''):
  if key in ('round_id','last_action_id','round_series_id') and a is not None:bind(key,a,b)
  if isinstance(a,dict) and isinstance(b,dict):
   for k,v in a.items():
    if k in b:align(v,b[k],k)
  elif isinstance(a,list) and isinstance(b,list):
   for x,y in zip(a,b):align(x,y,key)
 align(raw,events[-1]['response']);bind('round_series_id',series,events[-1]['request'].get('extra_data',{}).get('round_series_id'))

if __name__=='__main__':
 gid='FrenzyClusters';path=OUT/(gid+'.json');report=json.loads(path.read_text(encoding='utf8'));credentials=json.loads((PRIVATE/(gid+'.session.json')).read_text(encoding='utf8'));state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'))
 assert state.get('active_game') is None and credentials['game_id']==gid
 assert credentials['operation']['status']=='received' and credentials['last_response']['flow']['state']=='gamble_bonus'
 assert report['events'][-1]['request']['command']=='spin' and report['events'][-1]['request']['options']['purchased_feature_level']=='2'
 proof=json.loads((ROOT/'FrenzyClusters.protocol-evidence.json').read_text(encoding='utf8'));assert proof['portal_count']==5
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state['last_launch_epoch']=time.time();state['active_game']=gid;state['updated_at']=now();state.pop('queue_pass_finished_at',None);save(ROOT/'run-state.json',state)
 demo=Demo(report['game']);demo.api=trusted(credentials['api']);demo.page=credentials['page'];demo.csrf_name=credentials['csrf_name'];demo.csrf_value=credentials['csrf_value'];demo.series=credentials['series'];demo.last_response=credentials['last_response'];demo.events=report['events'];demo.money_checks=report['checks'];restore_aliases(demo.clean,demo.events,demo.last_response,demo.series)
 jar=next(h.cookiejar for h in demo.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in credentials['cookies']:jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 template=copy.deepcopy(report['declared_modes'][-1]);assert template['options']['purchased_feature_level']=='2';variants=[]
 for portal in range(5):
  mode=copy.deepcopy(template);mode['name']=template['name']+'/portal:'+str(portal);mode['selected_portal']=portal;variants.append(mode)
 report['declared_modes']=report['declared_modes'][:-1]+variants;report['status']='running';report.pop('reason',None);save(path,report)
 try:
  # Existing purchase already debited. First HTTP command will be gamble_bonus, never spin.
  start=len(demo.events)-1;mode=variants[0];demo.active_mode=mode;final=demo.settle(demo.last_response);demo.prev=final
  before=demo.events[start-1]['response']['balance'];wins=sum(e.get('response',{}).get('outcome',{}).get('win',0) for e in demo.events[start:]);expected=before['wallet']+before['game']-mode['cost_native']+wins;actual=final['balance']['wallet']+final['balance']['game'];ok=expected==actual;demo.money_checks.append(dict(kind='resumed_round_balance',expected=expected,actual=actual,ok=ok))
  if not ok:raise RuntimeError('Resumed round monetary audit needs review')
  report['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(demo.events)-1,final_balance=final['balance'],final_state='closed',win_native=wins,resumed_existing_purchase=True));report['events']=demo.events;report['checks']=demo.money_checks;save(path,report)
  init=report['events'][0]['response']
  for mode in variants[1:]:
   report['modes'].append(demo.run_mode(mode,init));report['events']=demo.events;report['checks']=demo.money_checks;save(path,report)
  report['status']='complete_declared_modes' if all(x['status']=='closed' for x in report['modes']) else 'partial'
 except Exception as e:report['status']='needs_review';report['reason']=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__
 report['events']=demo.events;report['checks']=demo.money_checks;report['finished_at']=now();save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(x['status']=='closed' for x in report['modes']),report='live/'+gid+'.json');state['active_game']=None;state['updated_at']=now();save(ROOT/'run-state.json',state)
 print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],flush=True)
