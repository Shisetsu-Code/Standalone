"""Finish only the received Book of Cats V1 feature using source-proved free spin wire."""
import json,copy,time,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import prove_old_slot
from old_slots import free_result
from classic_gamble import check_finish
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='BookOfCats';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore(gid);meta=prove_old_slot(gid,d.opener);pending=r.get('pending_mode',{});mode=pending.get('mode');start=pending.get('first_event')
 resume_free='--resume-received-free' in sys.argv
 if not mode or not pending.get('native_price_checked') or len(r['modes'])!=1 or start!=len(d.events)-(2 if resume_free else 1) or d.events[start]['request'].get('options')!=mode['options'] or not meta.get('v1_freespin_spin_verified') or d.last_response.get('game',{}).get('state')!='freespin':raise RuntimeError('Unexpected paid feature state; no input')
 recovered=None
 if resume_free:
  if r.get('reason')!='Unverified native V1 amounts' or d.events[-1]['request'].get('options')!={'bets':mode['options']['bets']}:raise RuntimeError('Not the classified received free-spin schema case')
  recovered=free_result(d.events[-2]['response'],d.events[-1]['response'],d.events[-1]['request']['options'],meta)
 total_win=d.events[start]['response'].get('result',{}).get('total')
 if type(total_win) is not int:raise RuntimeError('Trigger native payout missing')
 archive=ROOT/'live'/'attempts'/(gid+('.before-cumulative-free-resume.json' if resume_free else '.before-v1-freespin-finish.json'))
 if archive.exists():raise RuntimeError('Finish previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+('.before-cumulative-free-resume.session.json' if resume_free else '.before-v1-freespin-finish.session.json'));backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);free_events=[];free_results=[]
 if recovered:
  event=len(d.events)-1;d.money_checks.append(dict(event=event,**recovered['check']));free_events.append(event);free_results.append(dict(event=event,win_native=recovered['win_native'],win_origin=recovered.get('win_origin','native_total')));total_win+=recovered['win_native']
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live'/(gid+'.json');r.update(status='running',protocol_metadata=meta);r.pop('reason',None);save(path,r)
 try:
  for _ in range(500):
   current=d.last_response;game=current.get('game',{});available=current.get('available_commands',[])
   if game.get('state')=='closed':break
   index=len(d.events)
   if game.get('state')=='freespin' and game.get('freespins_left',0)>0 and 'spin' in available:
    options={'bets':dict(mode['options']['bets'])};response=d.call('spin',options);checked=free_result(current,response,options,meta);d.money_checks.append(dict(event=index,**checked['check']));free_events.append(index);free_results.append(dict(event=index,win_native=checked['win_native'],win_origin=checked.get('win_origin','native_total')));total_win+=checked['win_native']
   elif game.get('state')=='check_card' and 'finish' in available and meta.get('finish_command_verified'):
    response=d.call('finish');d.money_checks.append(dict(event=index,**check_finish(current,response,meta)));meta.setdefault('unresolved',[]).append('Card gamble advertised at feature end; collect verified, card choices still pending')
   else:raise RuntimeError('Unknown V1 feature continuation; native state preserved')
   r.update(events=d.events,checks=d.money_checks);save(path,r)
  else:raise RuntimeError('V1 feature continuation bound; state retained')
  before=d.events[start-1]['response']['balance'];win=total_win;expected=before-mode['cost_native']+win;actual=d.last_response['balance'];check=dict(kind='v1_feature_round_balance',expected=expected,actual=actual,cost_native=mode['cost_native'],win_native=win,ok=expected==actual);d.money_checks.append(check)
  if not check['ok']:raise RuntimeError('V1 complete feature native balance mismatch')
  r['modes'].append(dict(mode=mode,status='closed',first_event=start,last_event=len(d.events)-1,final_balance=actual,final_state='closed',win_native=win,free_spin_events=free_events,free_spin_results=free_results,resumed_existing_purchase=True));r.pop('pending_mode',None);r.update(checks=d.money_checks,status=completion_status(r,meta));r.pop('error_type',None)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'],'free_spins',len(free_events))
