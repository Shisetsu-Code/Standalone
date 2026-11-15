"""Continue received, already paid OGA combined bonus states; never replay the purchase."""
import json,copy,time,hashlib,sys,http.cookiejar,urllib.request,shutil
from fractions import Fraction
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from hyperhive_adapter import Hyperhive
from oga_classic import continuation_contracts,customize
from analyze import Sanitizer
def public_events(raw):
 clean=Sanitizer();events=[]
 for index,event in enumerate(raw):
  e=copy.deepcopy(event);e['request']['id']='rpc-'+str(index+1)
  if 'id' in e.get('response',{}):e['response']['id']='rpc-'+str(index+1)
  events.append(clean.clean(e))
 return events
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid=sys.argv[1]
 if gid not in ['TheGodfather3PillarsOfPower','RocketEruptionTripleBlast']:raise ValueError('Unprepared combined bonus')
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 path=ROOT/'live'/(gid+'.json');report=json.loads(path.read_text(encoding='utf8'));private=PRIVATE/'hyperhive'/(gid+'.session.json');data=json.loads(private.read_text(encoding='utf8'));metadata=copy.deepcopy(data['metadata'])
 if not data.get('fresh_demo') or data['game_id']!=gid or data['status']!='received' or data['initial']['result']['currency']!='FUN' or data['last_result'].get('final') is not False:raise RuntimeError('Only a received open fresh FUN round can be continued')
 source=(PRIVATE/'research'/'frontends'/gid/'game.js').read_text(encoding='utf8')
 if hashlib.sha256(source.encode()).hexdigest()!=metadata['source_sha256']:raise RuntimeError('Source version differs from the tested context')
 metadata['classic_continuations']=continuation_contracts(source)
 if public_events(data['events'])!=report['events']:raise RuntimeError('Private/public evidence differs; no input sent')
 if data['last_result']!=data['events'][-1]['response']['result']:raise RuntimeError('Checkpoint does not match last received result')
 mode=report['declared_modes'][len(report['modes'])];start=len(report['events'])-1;trigger=data['events'][-1]['request']['params']['req']
 if trigger.get('purchased_feature')!=mode['feature'] or trigger.get('custom_req')!=customize(metadata,mode,mode['bet_native'],'spin',True):raise RuntimeError('Pending purchase differs from declared mode')
 action=data['last_result']['resp']['engine']['gamestate']['triggeringDetails'].get('nextAction')
 if action not in metadata['classic_continuations']:raise RuntimeError('No source-verified combined action')
 archive=ROOT/'live'/'attempts'/(gid+'.before-combined-continuation.json')
 if archive.exists():raise RuntimeError('Recovery previously attempted; no automatic retry')
 save(archive,copy.deepcopy(report));backup=PRIVATE/'attempts'/(gid+'.before-combined-continuation.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,backup)
 parent=Demo(report['game']);parent.page=data['endpoint'].rsplit('/api',1)[0]+'/hyperhive';parent.events=report['events'];parent.money_checks=report.get('checks',[])
 jar=next(handler.cookiejar for handler in parent.opener.handlers if isinstance(handler,urllib.request.HTTPCookieProcessor))
 for c in data.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 h=Hyperhive(parent,{'play_token':data['token']});h.raw_events=data['events'];h.initial=data['initial'];h.last=data['last_result'];h.last_response=data['last_response'];h.metadata=metadata
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(ROOT/'run-state.json',state);report.update(status='running',protocol_metadata=metadata);report.pop('reason',None);save(path,report)
 try:
  before=data['events'][start-1]['response']['result']['balance'];total=Fraction(0);r=h.last
  for _ in range(500):
   win=r.get('resp',{}).get('win')
   if type(win) not in [int,float]:raise RuntimeError('Unverified OGA incremental win')
   total+=Fraction(str(win))
   if r.get('final') is True:break
   action=r.get('resp',{}).get('engine',{}).get('gamestate',{}).get('triggeringDetails',{}).get('nextAction')
   if not isinstance(action,str) or action not in set(metadata['classic_continuations'])|{'freespin','respin','jackpot','bonus','cascade','cascadefg'}:raise RuntimeError('Unrecognized received continuation; state retained')
   req=dict(bet=mode['bet_native'],bet_type='bet',custom_req=customize(metadata,mode,mode['bet_native'],action,False));r=h.request('play',req)['result'];parent.events=public_events(h.raw_events);report.update(events=parent.events,checks=parent.money_checks);save(path,report)
  else:raise RuntimeError('Continuation bound; round retained')
  expected=Fraction(str(before))-mode['cost_native']+total;actual=Fraction(str(r['balance']));check=dict(kind='resumed_oga_round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=r['balance'],ok=expected==actual);parent.money_checks.append(check)
  if not check['ok']:raise RuntimeError('Native combined OGA round balance mismatch')
  report['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(parent.events)-1,final_balance=r['balance'],final_state='final',win_native=int(total) if total.denominator==1 else float(total),resumed_existing_purchase=True))
  for remaining in report['declared_modes'][len(report['modes']):]:
   report['modes'].append(h.run_mode(remaining,h.initial));parent.events=public_events(h.raw_events);report.update(events=parent.events,checks=parent.money_checks);save(path,report)
  report['status']=completion_status(report,metadata)
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=public_events(h.raw_events),checks=parent.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,report['status'],'closed',state['results'][gid]['modes_closed'])
