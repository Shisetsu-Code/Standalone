"""One source-derived owned selector GET diagnostic; no init/POST/wagers."""
import json,http.cookiejar,urllib.request
from run_demo_qa import ROOT,PRIVATE,save,now
from checkpoint_guard import acquire,require_inactive
from all_lucky_variants import VariantGate
from diagnose_all_lucky_redirect import observe_once
if __name__=='__main__':
 lock=acquire(ROOT/'runner.lock');state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));require_inactive(state)
 if (ROOT/'STOP').read_text(encoding='utf8').strip()!='CHECKPOINT_MAINTENANCE':raise ValueError('Pause main queue first')
 source=PRIVATE/'all-lucky-variants-v2';cfg=json.loads((source/'selector-bootstrap.json').read_text());request=json.loads((source/'request-checkpoint.json').read_text());owned=json.loads((PRIVATE/'AllLuckyClover.session.json').read_text());dest=PRIVATE/'all-lucky-redirect-observation'
 dest.mkdir(parents=True,exist_ok=False)
 jar=http.cookiejar.CookieJar()
 for c in owned['cookies']:jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));records=[]
 def persist(stage,payload):
  records.append(dict(stage=stage,payload=payload));save(dest/'checkpoints.json',records)
  if payload.get('last_launch_epoch'):
   state.update(active_game='AllLuckyClover5',last_launch_epoch=payload['last_launch_epoch'],updated_at=now());save(ROOT/'run-state.json',state)
 try:
  with VariantGate(ROOT,last_launch_epoch=state['last_launch_epoch'],lock_handle=lock,maintenance_authorized=True) as gate:
   result=observe_once(request,cfg,owned,opener,gate=gate,private_checkpoint=persist)
  public=result.public_summary();save(ROOT/'all-lucky-redirect-observed.json',public);print(json.dumps(public,ensure_ascii=False))
 except Exception as error:
  save(dest/'failure.json',dict(error_type=type(error).__name__,error=str(error)));print('AllLucky GET observation stopped',type(error).__name__)
 finally:state.update(active_game=None,updated_at=now());save(ROOT/'run-state.json',state)
