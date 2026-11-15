"""Exercise six source-backed card choices and collect, with bounded native minimum FUN rounds."""
import json,copy,time,shutil,sys
from run_demo_qa import ROOT,PRIVATE,save,now,completion_status
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import prove_old_slot,load_client
from old_slots import plan,paid_result
from classic_gamble import metadata,check_event,check_finish
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='AztecMagicDeluxe';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore(gid);meta=prove_old_slot(gid,d.opener);_,source=load_client(gid,d.opener);meta.update(metadata(source));normal=plan(r['events'][0]['response'],meta)[0]
 resume_loss='--resume-received-loss' in sys.argv
 if len(r['events'])!=(4 if resume_loss else 3) or r.get('modes') or not meta.get('finish_command_verified') or r['events'][1]['request'].get('options')!=normal['options']:raise RuntimeError('Unexpected prior round; no request')
 initial=r['events'][0]['response'];base=paid_result(initial,r['events'][1]['response'],normal,meta);first=check_event(r['events'][1]['response'],r['events'][2],meta);tested={first['choice']};operations=[dict(event=2,parent_round=0,**first)];checks=[dict(event=1,**base['check']),dict(event=2,**first)];rounds=[];active_round=dict(first_event=1,before_balance_native=initial['balance'],cost_native=normal['cost_native'],base_win_native=base['win_native']);finished=False;search_spins=0
 if resume_loss:
  if r.get('reason')!='Unverified classic gamble native amounts' or r['events'][-1]['response'].get('game',{}).get('state')!='closed' or r['events'][-1]['response'].get('game',{}).get('bonus_game',{}).get('result')!='lose':raise RuntimeError('Only the classified received loss can be normalized')
  second=check_event(r['events'][2]['response'],r['events'][3],meta);tested.add(second['choice']);operations.append(dict(event=3,parent_round=0,**second));checks.append(dict(event=3,**second))
 archive=ROOT/'live'/'attempts'/(gid+('.after-received-loss-schema-review.json' if resume_loss else '.before-six-gamble-choices.json'))
 if archive.exists():raise RuntimeError('Exploration previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+('.after-received-loss-schema-review.session.json' if resume_loss else '.before-six-gamble-choices.session.json'));backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);d.money_checks=checks;d.protocol_metadata=meta;path=ROOT/'live'/(gid+'.json')
 def close_round(response):
  global active_round
  if active_round is None:raise RuntimeError('No recorded parent round')
  if response.get('game',{}).get('state')!='closed':raise RuntimeError('Parent round is not closed')
  entry=dict(active_round,last_event=len(d.events)-1,final_balance_native=response['balance'],derived_round_return_native=response['balance']-active_round['before_balance_native']+active_round['cost_native'],status='closed');rounds.append(entry)
  if len(rounds)==1:r['modes']=[dict(mode=normal,status='closed',first_event=entry['first_event'],last_event=entry['last_event'],final_balance=entry['final_balance_native'],final_state='closed',native_base_win=entry['base_win_native'],derived_round_return_native=entry['derived_round_return_native'],resumed_existing_round=True)]
  active_round=None
 def write_progress():
  pending=[v for v in meta['classic_gamble_choices'] if v not in tested];r.update(events=d.events,checks=d.money_checks,protocol_metadata=meta,exploration_rounds=rounds,open_exploration_round=active_round,bonus_operations=operations,bonus_mode_coverage=dict(source_types=meta['classic_gamble_choices'],tested=sorted(tested),pending=pending,collect_tested=finished,search_spins=search_spins,maximum_search_spins=100,scope='Each source choice once and collect. Search rounds use native minimum. No exhaustive card outcome/sequence claim.'));save(path,r)
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);r.update(status='running');r.pop('reason',None);r.pop('error_type',None);write_progress()
 try:
  for _ in range(250):
   current=d.last_response;phase=current.get('game',{}).get('state');available=current.get('available_commands',[]);pending=[v for v in meta['classic_gamble_choices'] if v not in tested]
   if phase=='closed' and active_round is not None:close_round(current)
   if not pending and finished and phase=='closed':break
   if phase=='check_card' and pending:
    if 'check_card' not in available:raise RuntimeError('Gamble not currently advertised')
    choice=pending[0];index=len(d.events);response=d.call('check_card',{'bet':choice});checked=check_event(current,d.events[-1],meta);d.money_checks.append(dict(event=index,**checked));tested.add(choice);operations.append(dict(event=index,parent_round=len(rounds),**checked))
   elif phase=='check_card' and not pending:
    if 'finish' not in available:raise RuntimeError('Collect not currently advertised')
    index=len(d.events);response=d.call('finish');checked=check_finish(current,response,meta);d.money_checks.append(dict(event=index,**checked));operations.append(dict(event=index,parent_round=len(rounds),command='finish',**checked));finished=True
   elif phase=='closed':
    if search_spins>=100:raise RuntimeError('Win-precondition search bound reached; unoffered choices remain pending')
    if 'spin' not in available:raise RuntimeError('Next native spin not available')
    if current['balance']<normal['cost_native']:raise RuntimeError('Insufficient FUN balance; no local top-up')
    index=len(d.events);response=d.call('spin',normal['options']);checked=paid_result(current,response,normal,meta);d.money_checks.append(dict(event=index,**checked['check']));search_spins+=1;active_round=dict(first_event=index,before_balance_native=current['balance'],cost_native=normal['cost_native'],base_win_native=checked['win_native'])
   else:raise RuntimeError('Unexpected bonus/choice state retained; no guessed continuation')
   if response.get('game',{}).get('state')=='closed' and active_round is not None:close_round(response)
   write_progress()
  else:raise RuntimeError('Classic gamble action bound; state retained')
  meta['unresolved']=[] if len(tested)==len(meta['classic_gamble_choices']) and finished else ['Card choices or collect pending'];r['status']=completion_status(r,meta)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r['finished_at']=now();write_progress();state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r.get('modes',[])),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'gamble_choices',sorted(tested),'collect',finished,'search_spins',search_spins)
