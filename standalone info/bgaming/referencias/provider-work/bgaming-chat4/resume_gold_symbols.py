"""Resume a paid Maneki bonus after a source-proved field deletion, not a new purchase."""
import json,copy,time,http.cookiejar,urllib.request,shutil,sys
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,completion_status,trusted
from checkpoint_guard import acquire,require_inactive
from legacy_metadata import prove_gold_symbols
from legacy_recovery import adopt_observed_init
from resume_frenzy import restore_aliases
from gold_symbols import plan
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');gid=sys.argv[1]
 if gid not in ['Maneki88Fortunes','Maneki88Gold']:raise ValueError('Unprepared selector recovery')
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise RuntimeError('Pause first')
 path=ROOT/'live'/(gid+'.json');r=json.loads(path.read_text(encoding='utf8'));private=PRIVATE/(gid+'.session.json');data=json.loads(private.read_text(encoding='utf8'));events=r['events'];rejected=events[-1]
 if not data.get('fresh_demo') or data['game_id']!=gid or data.get('operation',{}).get('status')!='http_rejection' or rejected.get('status')!=422 or rejected.get('response',{}).get('errors')!=[{'code':203,'desc':'invalid_options'}] or rejected['request'].get('command')!='freespin' or set(rejected['request'].get('options',{}))!={'gold_symbols_count'}:raise RuntimeError('Only the classified rejected continuation may be corrected')
 d=Demo(r['game']);d.api=trusted(data['api']);d.page=data['page'];d.csrf_name=data['csrf_name'];d.csrf_value=data['csrf_value'];d.series=data['series'];d.last_response=data['last_response'];d.events=events;d.money_checks=r['checks'];restore_aliases(d.clean,events[:-1],d.last_response,d.series)
 if d.clean.clean(d.last_response)!=events[-2]['response'] or d.clean.clean(data['last_request'])!=rejected['request']:raise RuntimeError('Accepted/rejected private checkpoints differ from public evidence')
 jar=next(handler.cookiejar for handler in d.opener.handlers if isinstance(handler,urllib.request.HTTPCookieProcessor))
 for c in data['cookies']:jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 meta=prove_gold_symbols(gid,d.opener)
 if not meta.get('gold_symbols_removed_before_freespins'):raise RuntimeError('Deletion before freespins not proved')
 modes=plan(events[0]['response'],meta);mode=modes[len(r['modes'])];trigger=len(events)-2
 if events[trigger]['request'].get('command')!='spin' or events[trigger]['request'].get('options')!=mode['options'] or d.last_response.get('flow',{}).get('state')!='freespins':raise RuntimeError('Already-paid trigger does not match prepared mode')
 archive=ROOT/'live'/'attempts'/(gid+'.before-freespin-selector-removal.json')
 if archive.exists():raise RuntimeError('Recovery previously attempted; no retry')
 save(archive,copy.deepcopy(r));backup=PRIVATE/'attempts'/(gid+'.before-freespin-selector-removal.session.json');backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(private,backup)
 current=adopt_observed_init(d,r,gid);d.protocol_metadata=meta;d.active_mode=mode
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state);r.update(status='running',protocol_metadata=meta,declared_modes=modes,events=d.events);r.pop('reason',None);r.pop('error_type',None);save(path,r)
 try:
  final=d.settle(current);d.prev=final;r['modes'].append(dict(mode=mode,status='closed',first_event=trigger,last_event=len(d.events)-1,final_balance=final['balance'],final_state=final['flow']['state'],resumed_existing_purchase=True))
  for remaining in modes[len(r['modes']):]:
   r['modes'].append(d.run_mode(remaining,events[0]['response']));r.update(events=d.events,checks=d.money_checks);save(path,r)
  r['status']=completion_status(r,meta)
 except Exception as e:r.update(status='needs_review',reason=str(e) if isinstance(e,(RuntimeError,ValueError,KeyError)) else type(e).__name__)
 r.update(events=d.events,checks=d.money_checks,finished_at=now());save(path,r);state['results'][gid]=dict(status=r['status'],modes_closed=sum(m['status']=='closed' for m in r['modes']),report='live/'+gid+'.json');state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state);print(gid,r['status'],'closed',state['results'][gid]['modes_closed'])
