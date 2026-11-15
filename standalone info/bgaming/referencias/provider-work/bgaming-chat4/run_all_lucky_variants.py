"""Parent CLI: fresh selector and its four native line-count variants, one/minute."""
import json,re,time,urllib.request,urllib.error,copy,hashlib,base64
from diagnose_all_lucky_redirect import OfficialRedirectHandler,_opener,parse_body
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,Demo,save,now,trusted,completion_status
from checkpoint_guard import acquire,require_inactive
from all_lucky_variants import SelectorPreparer,VariantGate,VARIANTS,official_url

if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause queue before isolated selector execution')
 prior=ROOT/'all-lucky-variants-live.json'
 if prior.exists():
  old=json.loads(prior.read_text(encoding='utf8'));archive=ROOT/'all-lucky-variants-before-official-redirect-support.json'
  if old.get('variant_reports') or archive.exists():raise ValueError('Existing selector attempts require review')
  save(archive,old)
 dest=ROOT/'live/selector-variants';dest.mkdir(parents=True,exist_ok=True)
 if any((dest/(gid+'.json')).exists() for gid in VARIANTS):raise ValueError('Existing variant attempts require received-state review, no replay')
 game=next(g for g in json.loads((ROOT/'catalog-live.json').read_text())['games'] if g['game_id']=='AllLuckyClover')
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state.update(active_game='AllLuckyClover',last_launch_epoch=time.time(),updated_at=now());save(ROOT/'run-state.json',state)
 d=Demo(game);private=PRIVATE/'all-lucky-variants-v3';private.mkdir(parents=True,exist_ok=True);records=[];aggregate=dict(game=game,status='running',events=[],modes=[],declared_modes=[],variant_reports=[])
 def checkpoint(stage,payload):
  save(private/'checkpoint.json',dict(stage=stage,payload=payload))
  if payload.get('last_launch_epoch'):
   state.update(last_launch_epoch=payload['last_launch_epoch'],active_game=payload.get('variant','AllLuckyClover'),updated_at=now());save(ROOT/'run-state.json',state)
 def fetch(url):
  with d.opener.open(urllib.request.Request(official_url(url),headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:
   if response.url!=url:raise ValueError('Static source redirected')
   return response.read()
 def request_json(method,url,headers,body):
  marker=dict(method=method,url=url,headers=headers,body=body.decode('utf8') if body else None,status='sending');save(private/'request-checkpoint.json',marker)
  try:
   selected_opener=_opener(OfficialRedirectHandler(checkpoint),d.opener) if method=='GET' else d.opener
   with selected_opener.open(urllib.request.Request(official_url(url),data=body,headers=dict(headers,**{'User-Agent':'Mozilla/5.0'}),method=method),timeout=45) as response:
    official_url(response.url);raw=response.read();marker.update(final_url=response.url,http_status=response.status,response_headers=list(response.headers.items()),response_body_base64=base64.b64encode(raw).decode(),response_sha256=hashlib.sha256(raw).hexdigest());save(private/'request-checkpoint.json',marker)
    kind,result=parse_body(raw)
    if not isinstance(result,dict) or kind not in ('bootstrap_options_json','json_other'):raise ValueError('Native selector/API JSON contract changed')
   marker.update(status='received',response=result);save(private/'request-checkpoint.json',marker);records.append(copy.deepcopy(marker));save(private/'requests.json',records);return result
  except Exception as error:
   body=error.read() if isinstance(error,urllib.error.HTTPError) else b''
   marker.update(status='http_rejection' if isinstance(error,urllib.error.HTTPError) else 'uncertain_or_rejected',error_type=type(error).__name__,error=str(error),http_status=getattr(error,'code',None),response_body=body.decode('utf8',errors='replace'));save(private/'request-checkpoint.json',marker);raise
 try:
  with d.opener.open(urllib.request.Request(trusted(game['demo_url']),headers={'User-Agent':'Mozilla/5.0'}),timeout=45) as response:d.page=trusted(response.url);html=response.read().decode('utf8')
  match=re.search(r'window\.__OPTIONS__\s*=\s*',html)
  if not match:raise ValueError('Fresh selector bootstrap missing')
  cfg,_=json.JSONDecoder().raw_decode(html[match.end():]);save(private/'selector-bootstrap.json',cfg)
  if cfg.get('identifier')!='AllLuckyClover' or cfg.get('currency')!='FUN' or cfg.get('server_id')!='demo':raise ValueError('Selector identity differs')
  d.api=trusted(cfg['api']);d.csrf_name=cfg['csrfTokenHeaderName'];d.csrf_value=cfg['csrfTokenHeaderValue'];initial=d.call('init');save(private/'selector-init.json',initial)
  aggregate['selector_initial']=d.clean.clean(initial)
  with VariantGate(ROOT,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
   preparer=SelectorPreparer(cfg,initial,fresh_suite_owned=True,fetch_source=fetch,request_json=request_json,private_checkpoint=checkpoint,gate=gate)
   for gid in VARIANTS:
    prepared=preparer.prepare(gid);variant=Demo(dict(game,game_id=gid,title=gid));variant.opener=d.opener;variant.page=d.page;variant.api=trusted(prepared.bootstrap['api']);variant.csrf_name=prepared.bootstrap['csrfTokenHeaderName'];variant.csrf_value=prepared.bootstrap['csrfTokenHeaderValue'];variant.protocol='legacy-v1-slots';variant.protocol_metadata=prepared.metadata;variant.last_response=prepared.initial;variant.prev=prepared.initial
    variant.events=[dict(time=now(),request={'command':'init'},response=variant.clean.clean(prepared.initial),status=200,kind='fresh_selector_variant_init')];variant.checkpoint(dict(status='received',command='init'))
    report=dict(game=variant.game,status='running',protocol=variant.protocol,protocol_metadata=variant.protocol_metadata,events=variant.events,checks=[],modes=[],declared_modes=prepared.modes,selector_preparation=prepared.public_record())
    path=dest/(gid+'.json');save(path,report)
    try:
     for mode in prepared.modes:
      report['modes'].append(variant.run_mode(mode,prepared.initial));report.update(events=variant.events,checks=variant.money_checks);save(path,report)
     report['status']=completion_status(report,variant.protocol_metadata)
    except Exception as error:report.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
    report.update(events=variant.events,checks=variant.money_checks,finished_at=now());save(path,report);aggregate['variant_reports'].append(dict(game_id=gid,status=report['status'],report=str(path.relative_to(ROOT))))
    print(gid,report['status'],'closed',sum(m['status']=='closed' for m in report['modes']),flush=True)
    if report['status']=='needs_review':break
  aggregate['status']='complete_declared_modes' if len(aggregate['variant_reports'])==4 and all(x['status']=='complete_declared_modes' for x in aggregate['variant_reports']) else 'partial'
 except Exception as error:aggregate.update(status='needs_review',reason=str(error) if isinstance(error,(ValueError,RuntimeError,KeyError)) else type(error).__name__)
 finally:
  aggregate['finished_at']=now();save(ROOT/'all-lucky-variants-live.json',aggregate);state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
 print('AllLucky selector',aggregate['status'],aggregate.get('reason',''),flush=True)
