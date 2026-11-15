"""Non-wagering init observation of fresh QA FUN contexts; the provider may refresh its demo balance."""
import json,urllib.request,urllib.error,http.cookiejar,copy,hashlib,uuid,sys
from run_demo_qa import ROOT,PRIVATE,save,now,trusted
from analyze import Sanitizer
def reconcile(gid):
 classic=PRIVATE/(gid+'.session.json');rpc=PRIVATE/'hyperhive'/(gid+'.session.json');path=rpc if rpc.exists() else classic;data=json.loads(path.read_text(encoding='utf8'));assert data['fresh_demo'] and data['game_id']==gid
 jar=http.cookiejar.CookieJar()
 for c in data.get('cookies',[]):jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json','Accept':'application/json'}
 if path==rpc:
  endpoint=trusted(data['endpoint']);origin=endpoint.rsplit('/api',1)[0];q=dict(id=str(uuid.uuid4()),jsonrpc='2.0',method='init',params={'token':data['token']})
  if data.get('metadata',{}).get('engine')=='cocos':q['params']['req']={}
  headers.update(Origin=origin,Referer=origin+'/')
 else:
  endpoint=trusted(data['api']);q=dict(command='init',extra_data={'round_series_id':data['series']});headers.update(Origin='https://demo.bgaming-network.com',Referer=data['page']);headers[data['csrf_name']]=data['csrf_value']
 try:
  with opener.open(urllib.request.Request(endpoint,data=json.dumps(q).encode(),headers=headers),timeout=45) as response:raw=response.read();status=response.status
 except urllib.error.HTTPError as e:raw=e.read();status=e.code
 except Exception as e:print(gid,'Init observation transport error',type(e).__name__,flush=True);return
 try:r=json.loads(raw)
 except ValueError:r=dict(body_format='non_json',bytes=len(raw))
 private=dict(game_id=gid,time=now(),request=q,response=r,status=status,response_sha256=hashlib.sha256(raw).hexdigest(),original_checkpoint=str(path.relative_to(PRIVATE)));save(PRIVATE/'readback'/(gid+'.json'),private)
 clean=Sanitizer();public=copy.deepcopy(private)
 if 'id' in q:public['request']['id']='rpc-reconcile';public['response']['id']='rpc-reconcile'
 save(ROOT/'reconciliation-live'/(gid+'.json'),clean.clean(public));result=r.get('result',r);print(gid,'status',status,'balance',result.get('balance'),'flow',result.get('flow',{}).get('state'),'rpc_state_present',result.get('state') is not None,'has_error',bool(r.get('error')),flush=True)
if __name__=='__main__':
 for gid in sys.argv[1:]:reconcile(gid)
