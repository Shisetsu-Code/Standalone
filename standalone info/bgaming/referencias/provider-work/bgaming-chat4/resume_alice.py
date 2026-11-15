"""Resume the already bought Alice bonus, then exercise source-defined card/gamble policies in FUN."""
import json,time,sys,copy
from run_demo_qa import ROOT,save,now,modes_from_init,completion_status
from checkpoint_guard import acquire
from legacy_recovery import restore,adopt_observed_init
from legacy_metadata import prove_alice_choices
if __name__=='__main__':
 runner_lock_handle=acquire(ROOT/'runner.lock');gid='AliceWonderLuck';state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games before restoring Alice')
 demo,report=restore(gid);metadata=prove_alice_choices(gid,demo.opener);initial=report['events'][0]['response'];modes=modes_from_init(initial,metadata)
 if demo.last_response['flow']['state']!='gamble_bonus':raise RuntimeError('Original Alice entry state changed')
 index=len(report['modes']);mode=modes[index];trigger=len(demo.events)-1
 for old,new in zip(report['modes'],modes):
  if old['mode']['options']!=new['options'] or old['mode']['cost_native']!=new['cost_native']:raise RuntimeError('Previous coverage does not match source plan')
 if demo.events[-1]['request'].get('command')!='spin' or demo.events[-1]['request']['options']!=mode['options']:raise RuntimeError('Original paid trigger does not match source plan')
 archive=ROOT/'live'/'attempts'/(gid+'.before-choice-recovery.json')
 if archive.exists():raise RuntimeError('Choice recovery was already attempted; inspect checkpoint before repeating')
 save(archive,copy.deepcopy(report));current=adopt_observed_init(demo,report,gid);demo.protocol_metadata=metadata;demo.active_mode=mode;demo.alice_progress={};demo.choice_actions=[];report['superseded_declared_modes']=report['declared_modes'];report['declared_modes']=modes
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state);path=ROOT/'live'/(gid+'.json');report.update(protocol_metadata=metadata,status='running',events=demo.events);report.pop('reason',None);save(path,report)
 try:
  final=demo.settle(current);demo.prev=final;report['modes'].append(dict(mode=mode,status='closed',first_event=trigger,last_event=len(demo.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True,choice_actions=demo.choice_actions,manual_card_indices=demo.alice_progress.get('used_indices',[])));report.update(events=demo.events,checks=demo.money_checks);save(path,report)
  for mode in modes[len(report['modes']):]:
   report['modes'].append(demo.run_mode(mode,initial));report.update(events=demo.events,checks=demo.money_checks);save(path,report);print(gid,mode['name'],report['modes'][-1]['status'],flush=True)
  report['status']=completion_status(report,metadata)
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 actions=[a for m in report['modes'] for a in m.get('choice_actions',[])];indices=sorted({a['options']['index'] for a in actions if a['command']=='pick_cards' and a['options'].get('mode')=='any'});report['choice_coverage']=dict(card_index_contract=[0,metadata['card_count']-1],manual_indices_tested=indices,commands_observed=sorted({a['command'] for a in actions}),pick_modes_observed=sorted({a['options']['mode'] for a in actions if a['command']=='pick_cards'}),scope=metadata['scope'])
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=sum(m['status']=='closed' for m in report['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state);print(gid,report['status'],'closed',state['results'][gid]['modes_closed'],'manual indices',indices,flush=True)
