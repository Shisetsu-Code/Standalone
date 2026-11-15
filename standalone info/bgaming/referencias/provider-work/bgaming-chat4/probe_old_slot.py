"""One source-verified minimum FUN line spin, preserved for schema review; never retries."""
import json,time,copy,sys
from run_demo_qa import ROOT,save,now
from checkpoint_guard import acquire
from legacy_recovery import restore
from legacy_metadata import prove_old_slot
from old_slots import plan
if __name__=='__main__':
 runner_lock_handle=acquire(ROOT/'runner.lock');gid=sys.argv[1];state_path=ROOT/'run-state.json';state=json.loads(state_path.read_text(encoding='utf8'))
 if state.get('active_game') or (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause between games first')
 demo,report=restore(gid)
 if report.get('modes') or any(e['request'].get('command')!='init' for e in report['events']):raise RuntimeError('Existing gameplay: no duplicate probe')
 meta=prove_old_slot(gid,demo.opener);modes=plan(demo.last_response,meta);mode=modes[0];archive=ROOT/'live'/'attempts'/(gid+'.before-v1-slot-probe.json')
 if archive.exists():raise RuntimeError('Probe previously attempted; no replay')
 save(archive,copy.deepcopy(report));time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(last_launch_epoch=time.time(),active_game=gid,updated_at=now());save(state_path,state);report.update(protocol='legacy-v1-slots',protocol_metadata=meta,declared_modes=modes,status='running');demo.protocol_metadata=meta;demo.active_mode=mode;path=ROOT/'live'/(gid+'.json');save(path,report)
 try:r=demo.call(mode['command'],mode['options']);report.update(status='needs_review',reason='Native v1 slot result captured; review settlement schema before any continuation');print(gid,'received keys',list(r),'commands',r.get('available_commands'),'game',r.get('game'),'balance',r.get('balance'),flush=True)
 except Exception as e:report.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 report.update(events=demo.events,checks=demo.money_checks,finished_at=now());save(path,report);state['results'][gid]=dict(status=report['status'],modes_closed=0,report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(state_path,state)
