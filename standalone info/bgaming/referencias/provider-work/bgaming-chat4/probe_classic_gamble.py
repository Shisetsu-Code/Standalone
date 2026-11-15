"""One source-proved check_card in an existing received FUN round, then stop for schema review."""
import json,copy,time,shutil
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
from legacy_recovery import restore
from legacy_metadata import load_client
from classic_gamble import metadata
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid='AztecMagicDeluxe';state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 d,r=restore(gid);source_meta,source=load_client(gid,d.opener);meta=metadata(source);current=d.last_response
 if current.get('game',{}).get('state')!='check_card' or 'check_card' not in current.get('available_commands',[]) or len(r.get('events',[]))!=2 or r['modes']:raise RuntimeError('Unexpected pending game; no request')
 currency=r['events'][0]['response']['options']['currency']
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise RuntimeError('Not FUN')
 archive=ROOT/'live'/'attempts'/(gid+'.before-classic-gamble-probe.json')
 if archive.exists():raise RuntimeError('Probe already attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-classic-gamble-probe.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PRIVATE/(gid+'.session.json'),backup);r['protocol_metadata'].update(meta);save(ROOT/'protocols'/(gid+'.classic-gamble.json'),dict(source=source_meta,**meta))
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);path=ROOT/'live'/(gid+'.json');r.update(status='running');save(path,r)
 try:
  response=d.call('check_card',{'bet':meta['classic_gamble_choices'][0]});r.update(status='needs_review',reason='Native classic gamble response received; settlement schema review pending');print('Received classic gamble','keys',list(response),'balance',response.get('balance'),'state',response.get('game',{}).get('state'),'is_win',response.get('game',{}).get('bonus_game',{}).get('isWin'),'stake',response.get('bets',{}).get('required_for_bonus_game'),'result_total',response.get('result',{}).get('total'),flush=True)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid].update(status=r['status']);state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
