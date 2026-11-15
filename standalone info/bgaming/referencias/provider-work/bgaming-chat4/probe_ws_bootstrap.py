"""Fresh official FUN launch + WS game_info only. Never sends make_bet."""
import json,re,time,urllib.request,http.cookiejar,sys,hashlib
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,Demo,trusted,save,now
from checkpoint_guard import acquire,require_inactive
from ws_crash_runtime import CrashBootstrap
from ws_crash_extra import metadata,mode_plan

def probe(gid,state):
 path=ROOT/'ws-bootstrap'/(gid+'.json')
 if path.exists():
  old=json.loads(path.read_text(encoding='utf8'))
  if old.get('reason')!='Non official public demo endpoint rejected' or old.get('events') or old.get('private_reference'):raise ValueError('Existing bootstrap evidence; explicit review required before another launch')
  archive=path.with_name(gid+'.before-static-origin-check.json')
  if archive.exists():raise ValueError('Already retried classified pre-socket validation failure')
  path.replace(archive)
 game=next(g for g in json.loads((ROOT/'catalog-live.json').read_text(encoding='utf8'))['games'] if g['game_id']==gid)
 proof=json.loads((ROOT/'protocols'/(gid+'.ws-prepared.json')).read_text(encoding='utf8'))
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])))
 state.update(active_game=gid,last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
 d=Demo(game);runtime=None;report=dict(game=game,status='running',phase='WS bootstrap only',events=[],modes=[])
 try:
  with d.opener.open(urllib.request.Request(trusted(game['demo_url']),headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
   d.page=trusted(response.url);html=response.read().decode('utf8')
  match=re.search(r'window\.__OPTIONS__\s*=\s*',html)
  if not match:raise ValueError('Fresh bootstrap options missing')
  cfg,_=json.JSONDecoder().raw_decode(html[match.end():])
  if cfg.get('currency')!='FUN' or cfg.get('server_id')!='demo' or cfg.get('identifier')!=gid:raise ValueError('Fresh demo identity differs')
  source_url=proof['source_url'];parsed=urlsplit(source_url)
  if parsed.scheme!='https' or parsed.hostname!='cdn.bgaming-network.com' or parsed.query or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('Reviewed static origin required')
  with d.opener.open(urllib.request.Request(source_url,headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
   if response.url!=source_url:raise ValueError('Static source redirected')
   raw=response.read()
  meta=metadata(gid,raw.decode('utf8'))
  jar=next(h.cookiejar for h in d.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
  import websocket
  def factory(url,**kwargs):
   request=urllib.request.Request(url.replace('wss://','https://',1));jar.add_cookie_header(request)
   try:return websocket.create_connection(url,cookie=request.get_header('Cookie'),**kwargs)
   except Exception as error:
    save(private/'handshake-error.json',dict(error_type=type(error).__name__,status=getattr(error,'status_code',None),headers=dict(getattr(error,'resp_headers',{}) or {}),body=str(getattr(error,'resp_body',''))))
    report['handshake_status']=getattr(error,'status_code',None)
    raise
  private=PRIVATE/'ws-probes'/(gid+'-'+str(int(time.time()*1000)))
  runtime=CrashBootstrap(d,cfg,meta,socket_factory=factory,private_dir=private,owned_fresh=True)
  context=runtime.initialize();report.update(status='bootstrap_verified',context=runtime._clean(context),declared_modes=mode_plan(meta,context),metadata=meta,private_reference=str(private.relative_to(PRIVATE)))
 except Exception as error:
  report.update(status='bootstrap_needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__)
 finally:
  if runtime:runtime.close()
  report.update(events=d.events,finished_at=now());save(path,report);state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
 print(gid,report['status'],report.get('reason',''),flush=True)

if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()=='CONTINUE':raise ValueError('Pause main queue before WS probe')
 for gid in sys.argv[1:]:
  if gid not in ['BInvestLive','DragonsCrash','GiftX','SpaceXY','TopEagle']:raise ValueError('Unprepared WS game')
  probe(gid,state)
