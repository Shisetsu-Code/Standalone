"""Continue Star Trek's paid bonus, then source-known choices/modes; preserve money anomalies."""
import json,copy,time,hashlib,sys,shutil
from fractions import Fraction
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from hyperhive_adapter import Hyperhive,plan_modes
from star_choices import metadata,next_request
from resume_oga_combined import public_events
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='StarTrekNextGen';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 path=ROOT/'live'/(gid+'.json');r=json.loads(path.read_text(encoding='utf8'));private=PRIVATE/'hyperhive'/(gid+'.session.json');data=json.loads(private.read_text(encoding='utf8'))
 if not data.get('fresh_demo') or data['game_id']!=gid or data['status']!='received' or data['initial']['result']['currency']!='FUN' or data['last_result'].get('final') is not False or data.get('cookies'):raise RuntimeError('Unexpected pending Star Trek context; no new request')
 p=PRIVATE/'research'/'frontends'/gid;source=(p/'game_game.min.js').read_text(encoding='utf8');integration=(p/'game_integration.min.js').read_text(encoding='utf8');meta=copy.deepcopy(data['metadata'])
 if hashlib.sha256(source.encode()).hexdigest()!=meta['source_sha256'] or hashlib.sha256((p/'game_media_definitions.json').read_bytes()).hexdigest()!=meta['definitions_sha256']:raise RuntimeError('Source/definition version changed')
 meta.update(metadata(source,integration));modes=plan_modes(data['initial'],meta)
 if public_events(data['events'])!=r['events'] or len(r['modes'])!=1 or len(modes)!=6:raise RuntimeError('Pending evidence/plan mismatch')
 mode=modes[1];start=len(r['events'])-1;q=data['events'][-1]['request']['params']['req']
 if q.get('custom_req')!=dict(mode['custom_params'],action='spin',exponent=2,**({'stake':mode['bet_native']} if meta['send_custom_stake'] else {})) or q.get('purchased_feature')!=mode['feature']:raise RuntimeError('Already-paid trigger does not match source plan')
 if next_request(data['last_result'],mode,meta)['custom_req']!={'action':'fs_choice','choice':1,'exponent':2}:raise RuntimeError('Not the source-verified first choice state')
 archive=ROOT/'live'/'attempts'/(gid+'.before-four-choice-continuation.json')
 if archive.exists():raise RuntimeError('Choice recovery previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-four-choice-continuation.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,backup)
 parent=Demo(r['game']);parent.page=data['endpoint'].rsplit('/api',1)[0]+'/hyperhive';parent.events=r['events'];parent.money_checks=r['checks'];h=Hyperhive(parent,{'play_token':data['token']});h.raw_events=data['events'];h.initial=data['initial'];h.last=data['last_result'];h.last_response=data['last_response'];h.metadata=meta
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);r.update(status='running',protocol_metadata=meta,declared_modes=modes);r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  before=data['events'][start-1]['response']['result']['balance'];wallet=Fraction(str(before))-mode['cost_native'];total=Fraction(0);current=h.last;choices=[];observations=[]
  for _ in range(500):
   win=current.get('resp',{}).get('win')
   if type(win) not in [int,float]:raise RuntimeError('Star Trek payout schema unknown')
   total+=Fraction(str(win));actual=Fraction(str(current['balance']))
   if current.get('final') is True:break
   if actual!=wallet:observations.append(dict(kind='native_nonfinal_balance_discontinuity',event=len(h.raw_events)-1,before_native=int(wallet),after_native=current['balance'],delta_native=int(actual-wallet),cause='unverified; not a gameplay win or local balance change'));wallet=actual
   request=next_request(current,mode,meta)
   if request['custom_req']['action']=='fs_choice':choices.append(request['custom_req']['choice'])
   current=h.request('play',request)['result'];parent.events=public_events(h.raw_events);r.update(events=parent.events,checks=parent.money_checks);save(path,r)
  else:raise RuntimeError('Star Trek continuation bound; state retained')
  expected=Fraction(str(before))-mode['cost_native']+total;check=dict(kind='resumed_star_native_round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=current['balance'],ok=expected==actual);parent.money_checks.append(check)
  if observations:r.setdefault('provider_state_observations',[]).extend(observations)
  r['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(parent.events)-1,final_balance=current['balance'],final_state='final',win_native=int(total) if total.denominator==1 else float(total),resumed_existing_purchase=True,choices_taken=choices,monetary_status='verified' if check['ok'] else 'unresolved_native_balance_discontinuity'))
  for remaining in modes[len(r['modes']):]:
   r['modes'].append(h.run_mode(remaining,h.initial));parent.events=public_events(h.raw_events);r.update(events=parent.events,checks=parent.money_checks);save(path,r)
  r['status']=completion_status(r,meta)
  if r['status']=='partial':r['reason']='Declared modes closed; native monetary discrepancy remains preserved for review'
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=public_events(h.raw_events),checks=parent.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
