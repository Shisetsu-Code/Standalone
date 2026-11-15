"""Normalize the already received Jungle normal result, then execute only its untested buy."""
import json,time,copy,shutil,http.cookiejar,urllib.request
from fractions import Fraction
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status
from hyperhive_adapter import Hyperhive,plan_modes
from resume_oga_combined import public_events
from rpc_extra import _win,_request
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 gid='JungleQueen';lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 path=ROOT/'live'/(gid+'.json');r=json.loads(path.read_text(encoding='utf8'));p=PRIVATE/'hyperhive'/(gid+'.session.json');d=json.loads(p.read_text(encoding='utf8'));archive=ROOT/'live/attempts/JungleQueen.before-native-string-read.json'
 if archive.exists() or r['modes'] or len(r['events'])!=2 or d.get('status')!='received' or not d.get('fresh_demo') or d['initial']['result']['currency']!='FUN' or d['last_result'].get('final') is not True or public_events(d['events'])!=r['events'] or d['last_result']!=d['events'][-1]['response']['result']:raise RuntimeError('Not the single received native normal round; do not replay')
 modes=plan_modes(d['initial'],r['protocol_metadata']);mode=modes[0]
 if len(modes)!=2 or d['events'][-1]['request']['params']['req']!=_request(mode):raise RuntimeError('Received request differs from source mode')
 win=_win(d['last_result'],'jungle-queen');expected=Fraction(str(d['initial']['result']['balance']))-mode['cost_native']+win
 if expected!=Fraction(str(d['last_result']['balance'])):raise RuntimeError('Received native normal round does not reconcile')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts/JungleQueen.before-native-string-read.session.json';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,backup)
 parent=Demo(r['game']);parent.page=d['endpoint'].rsplit('/api',1)[0]+'/hyperhive';parent.events=r['events'];parent.money_checks=r['checks'];jar=next(h.cookiejar for h in parent.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in d.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 h=Hyperhive(parent,{'play_token':d['token']});h.raw_events=d['events'];h.initial=d['initial'];h.last=d['last_result'];h.last_response=d['last_response'];h.metadata=r['protocol_metadata'];parent.money_checks.append(dict(kind='rpc_extra_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=h.last['balance'],ok=True));r['modes'].append(dict(mode=mode,status='closed',first_event=1,last_event=1,final_balance=h.last['balance'],final_state='final',normalized_existing_received_response=True,win_ratio=[win.numerator,win.denominator]));save(path,r)
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);r.update(status='running');r.pop('reason',None);r.pop('error_type',None)
 try:r['modes'].append(h.run_mode(modes[1],h.initial));r['status']=completion_status(r,h.metadata)
 except Exception as error:r.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
 r.update(events=public_events(h.raw_events),checks=parent.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
