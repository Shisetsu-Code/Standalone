"""One source-verified Book of Cats feature purchase in its own FUN QA context, then review."""
import json,copy,time,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import prove_old_slot
from old_slots import plan,paid_result
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='BookOfCats';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore(gid);meta=prove_old_slot(gid,d.opener);rb=json.loads((PRIVATE/'readback'/(gid+'.json')).read_text(encoding='utf8'));initial=rb['response'];currency=initial.get('options',{}).get('currency',{})
 if len(r['modes'])!=1 or r['modes'][0]['status']!='closed' or d.last_response.get('game',{}).get('state')!='closed' or rb.get('game_id')!=gid or rb['status']!=200 or rb['time']<=r['events'][-1]['time'] or rb['request'].get('command')!='init' or rb['request'].get('extra_data',{}).get('round_series_id')!=d.series or currency.get('code')!='FUN' or currency.get('subunits')!=100 or initial.get('game',{}).get('state')!='idle':raise RuntimeError('Unexpected closed FUN context/init; no purchase')
 modes=plan(initial,meta)
 if len(modes)!=2 or modes[0]['options']!=r['modes'][0]['mode']['options'] or not meta.get('v1_buy_feature_verified'):raise RuntimeError('Native minimum/source plan changed; no purchase')
 mode=modes[1]
 if initial['balance']<mode['cost_native']:raise RuntimeError('Insufficient FUN funds')
 archive=ROOT/'live'/'attempts'/(gid+'.before-v1-feature-buy.json')
 if archive.exists():raise RuntimeError('Feature previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-v1-feature-buy.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup)
 if initial['balance']!=d.last_response['balance']:r.setdefault('provider_state_observations',[]).append(dict(kind='native_init_balance_refresh',before_native=d.last_response['balance'],after_native=initial['balance'],event=len(d.events),note='Non-wagering init changed native FUN balance in an idle game; not a prize or local top-up'))
 d.events.append(dict(time=rb['time'],request=d.clean.clean(rb['request']),response=d.clean.clean(initial),status=rb['status'],response_sha256=rb['response_sha256'],kind='non_wagering_init_reconciliation'));d.last_response=initial;d.active_mode=mode;d.protocol_metadata=meta
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live'/(gid+'.json');r.update(status='running',protocol_metadata=meta,declared_modes=modes,events=d.events);r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  index=len(d.events);response=d.call(mode['command'],mode['options']);checked=paid_result(initial,response,mode,meta);d.money_checks.append(dict(event=index,**checked['check']));r.update(status='needs_review',reason='Native V1 feature purchase received; bonus continuation schema review pending',pending_mode=dict(mode=mode,first_event=index,native_price_checked=True));print('Book feature buy','cost',mode['cost_native'],'balance',response.get('balance'),'state',response.get('game',{}).get('state'),'commands',response.get('available_commands'),flush=True)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid].update(status=r['status']);state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
