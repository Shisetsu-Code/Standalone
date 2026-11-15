"""One fresh-session JSON-RPC demo action, with durable no-retry evidence."""
import json,urllib.request,urllib.error,uuid,hashlib,time
from pathlib import Path
from urllib.parse import urlsplit
from analyze import Sanitizer
from run_demo_qa import ROOT,PRIVATE,save,now,trusted
if __name__=='__main__':
 gid='HotRocketMegaPotz';capture=json.loads((PRIVATE/'browser'/gid/'capture.json').read_text(encoding='utf8'));events=[]
 for e in capture['records']:
  if e.get('kind')=='http' and e.get('method')=='POST' and e.get('contentType','').startswith('application/json'):
   q=json.loads(e['requestBody'])
   if q.get('method')=='init':initial=json.loads(e['body']);endpoint=trusted(e['url']);token=q['params']['token'];break
 else:raise RuntimeError('No captured fresh init')
 result=initial['result'];assert result['currency']=='FUN' and result['currency_attributes']['subunits']==100 and result['balance']==100000
 private=PRIVATE/'rpc'/(gid+'.session.json');assert not private.exists(),'Existing RPC probe state; never repeat an uncertain action'
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));assert state.get('active_game') is None
 time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state['last_launch_epoch']=time.time();state['active_game']=gid;state['updated_at']=now();save(ROOT/'run-state.json',state)
 bet=min(result['config']['bet_limits']);query={'id':str(uuid.uuid4()),'jsonrpc':'2.0','method':'play','params':{'token':token,'req':{'bet':bet,'bet_type':'bet','custom_req':{'exponent':result['currency_attributes']['exponent']}},'state_lock':result.get('state_lock','')}}
 session=dict(fresh_demo=True,game_id=gid,endpoint=endpoint,token=token,initial=initial,last_response=initial,last_request=query,status='sending',events=[]);save(private,session)
 u=urlsplit(endpoint);headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json','Accept':'application/json','Origin':u.scheme+'://'+u.netloc,'Referer':u.scheme+'://'+u.netloc+'/'}
 try:
  with urllib.request.urlopen(urllib.request.Request(endpoint,data=json.dumps(query).encode(),headers=headers),timeout=45) as r:raw=r.read();status=r.status
 except urllib.error.HTTPError as e:raw=e.read();status=e.code
 except Exception as e:session['status']='uncertain';session['error_type']=type(e).__name__;save(private,session);raise RuntimeError('Uncertain RPC response; no retry') from None
 try:response=json.loads(raw)
 except ValueError:response={'body_format':'non_json','bytes':len(raw)}
 session.update(last_response=response,status='received',events=[dict(time=now(),request=query,response=response,status=status,response_sha256=hashlib.sha256(raw).hexdigest())]);save(private,session)
 cleaner=Sanitizer();safe_query=dict(query,id='rpc-play-1');safe_response=dict(response,id='rpc-play-1');safe_initial=dict(initial,id='rpc-init-1')
 public=dict(provider='bgaming',game_id=gid,protocol='jsonrpc',endpoint=endpoint,initial=cleaner.clean(safe_initial),events=[dict(request=cleaner.clean(safe_query),response=cleaner.clean(safe_response),status=status,response_sha256=hashlib.sha256(raw).hexdigest())],requested_bet_native=bet)
 save(ROOT/'transport'/(gid+'.rpc-pilot.json'),public)
 if response.get('result',{}).get('final') is True:state['active_game']=None
 state['updated_at']=now();save(ROOT/'run-state.json',state)
 print('RPC status',status,'result keys',list(response.get('result',{})),'error',bool(response.get('error')),'final',response.get('result',{}).get('final'))
