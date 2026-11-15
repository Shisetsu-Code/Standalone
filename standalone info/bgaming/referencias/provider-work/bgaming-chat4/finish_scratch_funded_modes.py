"""Test only previously unfunded affordable packs, each in an independent fresh native FUN session."""
import json,time,copy,shutil
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status
from legacy_recovery import restore
from checkpoint_guard import acquire,require_inactive
if __name__=='__main__':
 gid='ThreeKingsScratch';lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 previous,r=restore(gid);path=ROOT/'live'/(gid+'.json');archive=ROOT/'live/attempts/ThreeKingsScratch.before-independent-funds-tests.json'
 if archive.exists() or r['status']!='partial' or len(r['modes'])!=12 or previous.last_response['flow']['state']!='closed':raise RuntimeError('Not the closed partially funded plan; no replay')
 selected=[i for i,m in enumerate(r['modes']) if m['status']=='insufficient_demo_balance' and m['mode']['cost_native']<=100000]
 if [r['modes'][i]['mode']['name'] for i in selected]!=['board:16/pack:100','board:20/pack:50']:raise ValueError('Affordable unexecuted packs differ')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts/ThreeKingsScratch.before-independent-funds-tests.session.json';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);r.setdefault('prior_insufficient_modes',[]).extend(copy.deepcopy(r['modes'][i]) for i in selected)
 for index in selected:
  time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
  demo=Demo(r['game']);demo.clean=previous.clean;demo.events=previous.events;demo.money_checks=previous.money_checks;mode=r['modes'][index]['mode'];r.update(status='running');save(path,r)
  try:
   before=previous.last_response['balance'];initial=demo.launch()
   if demo.protocol_metadata.get('source_sha256')!=r['protocol_metadata'].get('source_sha256') or not demo.protocol_metadata.get('scratch_packs_verified'):raise RuntimeError('Fresh scratch contract differs; no wager sent')
   demo.events[-1]['kind']='independent_fresh_fun_session_init';r.setdefault('provider_state_observations',[]).append(dict(kind='independent_fresh_fun_session',event=len(demo.events)-1,before_native=before,after_native=initial['balance'],note='Separate official FUN session for an unexecuted mode after prior round closed; no local balance modification or replay of a completed purchase.'))
   result=demo.run_mode(mode,initial);r['modes'][index]=result;r.update(events=demo.events,checks=demo.money_checks);save(path,r);previous=demo;print(mode['name'],result['status'],flush=True)
  except Exception as error:
   r.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__,events=demo.events,checks=demo.money_checks,finished_at=now());save(path,r);state.update(active_game=None,updated_at=now());state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');save(ROOT/'run-state.json',state);raise
  state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
 r.update(status=completion_status(r,r['protocol_metadata']),finished_at=now());r['remaining_funding_constraints']=[dict(mode=m['mode']['name'],cost_native=m['mode']['cost_native'],observed_fresh_demo_wallet_native=100000,reason='Minimum native purchase cost exceeds the native balance supplied by a fresh official demo. No balance fabricated.') for m in r['modes'] if m['status']=='insufficient_demo_balance'];save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
