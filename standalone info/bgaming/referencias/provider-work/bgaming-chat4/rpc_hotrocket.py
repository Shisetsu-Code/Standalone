"""Fresh FUN JSON-RPC Hot Rocket QA. No automatic retries or unknown choices."""
import json,urllib.request,urllib.error,uuid,time,hashlib,copy
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save,now,trusted
from analyze import Sanitizer
class RPC:
 def __init__(self):
  self.gid='HotRocketMegaPotz';self.private=PRIVATE/'rpc'/(self.gid+'.session.json');self.data=json.loads(self.private.read_text(encoding='utf8'));assert self.data['fresh_demo'] and self.data['status']=='received';self.endpoint=trusted(self.data['endpoint']);assert self.data['initial']['result']['currency']=='FUN';self.clean=Sanitizer()
 def call(self,feature=None,choice=None):
  last=self.data['last_response']['result'];bet=min(self.data['initial']['result']['config']['bet_limits']);req={'bet':bet,'bet_type':'bet','custom_req':{'exponent':2}}
  if feature:req['purchased_feature']=feature
  if choice is not None:req['custom_req']['choice']=choice
  q={'id':str(uuid.uuid4()),'jsonrpc':'2.0','method':'play','params':{'token':self.data['token'],'req':req,'state_lock':last.get('state_lock','')}}
  self.data.update(last_request=q,status='sending');save(self.private,self.data);u=urlsplit(self.endpoint);headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/json','Accept':'application/json','Origin':u.scheme+'://'+u.netloc,'Referer':u.scheme+'://'+u.netloc+'/'}
  time.sleep(.5)
  try:
   with urllib.request.urlopen(urllib.request.Request(self.endpoint,data=json.dumps(q).encode(),headers=headers),timeout=45) as r:raw=r.read();status=r.status
  except urllib.error.HTTPError as e:raw=e.read();status=e.code
  except Exception as e:self.data.update(status='uncertain',error_type=type(e).__name__);save(self.private,self.data);raise RuntimeError('Uncertain RPC response; never retry') from None
  try:r=json.loads(raw)
  except ValueError:r={'body_format':'non_json','bytes':len(raw)}
  self.data['events'].append(dict(time=now(),request=q,response=r,status=status,response_sha256=hashlib.sha256(raw).hexdigest()));self.data.update(last_response=r,status='received');save(self.private,self.data);self.export()
  if status!=200 or 'error' in r:raise RuntimeError('RPC rejection; inspect evidence before proceeding')
  return r['result']
 def export(self):
  events=[]
  for i,e in enumerate(self.data['events']):
   q=copy.deepcopy(e['request']);r=copy.deepcopy(e['response']);q['id']=r['id']='rpc-play-'+str(i+1);events.append(dict(time=e['time'],request=self.clean.clean(q),response=self.clean.clean(r),status=e['status'],response_sha256=e['response_sha256']))
  initial=copy.deepcopy(self.data['initial']);initial['id']='rpc-init-1';save(ROOT/'transport'/(self.gid+'.rpc-evidence.json'),dict(provider='bgaming',game_id=self.gid,protocol='jsonrpc',endpoint=self.endpoint,initial=self.clean.clean(initial),events=events))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--feature',choices=['freespin_chance','freespin_buy','high_freespin_buy']);p.add_argument('--choice',type=int,choices=[1,2]);p.add_argument('--continue-round',action='store_true');args=p.parse_args();rpc=RPC();last=rpc.data['last_response']['result'];assert last.get('final') is True or args.continue_round,'Pending round: explicit continuation required';r=rpc.call(args.feature,args.choice);print('final',r.get('final'),'balance',r.get('balance'),'resp keys',list(r.get('resp',{})));print('gamestate keys',list(r.get('resp',{}).get('engine',{}).get('gamestate',{})))
