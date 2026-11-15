"""Cocos request shapes recovered from the official Red and Hot Chilli client."""
import json,copy,urllib.request
from urllib.parse import urlsplit
from types import SimpleNamespace
from run_demo_qa import ROOT,PRIVATE,save
from hyperhive_adapter import Hyperhive
from analyze import Sanitizer
class CocosRPC:
 def __init__(self,gid='RedAndHotChilli'):
  self.gid=gid;s=json.loads((PRIVATE/'hyperhive'/(gid+'.session.json')).read_text(encoding='utf8'));assert s['fresh_demo'] and s['status']=='received'
  initial=s['initial'] or next(e['response'] for e in s['events'] if e['request']['method']=='init');assert initial['result']['currency']=='FUN' and initial['result']['currency_attributes']['subunits']==100
  origin=urlsplit(s['endpoint']).scheme+'://'+urlsplit(s['endpoint']).netloc;self.parent=SimpleNamespace(game={'game_id':gid},page=origin+'/hyperhive',opener=urllib.request.build_opener(),events=[],clean=Sanitizer(),bootstrap={},money_checks=[])
  self.h=Hyperhive(self.parent,{'play_token':s['token']});self.h.raw_events=s['events'];self.h.initial=initial;self.h.last=s['last_result'];self.h.metadata=json.loads((ROOT/'protocols'/(gid+'.cocos.json')).read_text(encoding='utf8'));self.bet=min(initial['result']['config']['bet_limits'])
 def export(self):
  clean=Sanitizer();events=[]
  for index,event in enumerate(self.h.raw_events):
   e=copy.deepcopy(event);e['request']['id']='rpc-'+str(index+1)
   if 'id' in e['response']:e['response']['id']='rpc-'+str(index+1)
   round_data=e['response'].get('result',{}).get('resp',{}).get('round',{})
   if 'id' in round_data:round_data['id']=clean.clean({'round_id':round_data['id']})['round_id']
   events.append(clean.clean(e))
  initial=copy.deepcopy(self.h.initial);initial['id']='rpc-init';save(ROOT/'transport'/(self.gid+'.cocos-evidence.json'),dict(provider='bgaming',game_id=self.gid,protocol='jsonrpc-cocos',initial=clean.clean(initial),metadata=self.h.metadata,events=events))
 def call(self,req):
  r=self.h.request('play',req);self.export();return r['result']
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--bid',type=int,choices=[0,1,2,3]);g.add_argument('--pick',nargs=2,type=int);g.add_argument('--decision',choices=['collect','gamble']);p.add_argument('--repeat-for-choice',action='store_true');a=p.parse_args();rpc=CocosRPC();last=rpc.h.last
 if a.bid is not None:
  assert last.get('final') is True,'Open round: no new purchase'
  if not a.repeat_for_choice:
   ready=True
   for e in rpc.h.raw_events:
    if e['request']['method']!='play':continue
    if ready and e['request']['params']['req'].get('bid')==a.bid:raise RuntimeError('Bid already started; do not repeat a wager')
    ready=e['response'].get('result',{}).get('final',False)
  req=dict(bet=rpc.bet,bet_type='bet',bid=a.bid)
  if a.bid:req['purchased_feature']=next(p['purchased_feature'] for p in rpc.h.metadata['products'] if p['bid']==a.bid)
 elif a.pick is not None:
  assert last.get('final') is False;req=dict(bet=rpc.bet,bet_type='bet',bid=last['resp']['round']['bet']['id'],custom_field={'fid':{'x':a.pick[0],'y':a.pick[1]}})
 else:
  assert last.get('final') is False;req=dict(bet=rpc.bet,bet_type='bet',custom_field={'fid':{'a':'no' if a.decision=='collect' else 'yes'}})
 result=rpc.call(req);resp=result.get('resp',{});round_data=resp.get('round',{});step=resp.get('step',{});print('final',result.get('final'),'balance',result.get('balance'),'bet',round_data.get('bet'),'round win',round_data.get('win'),'step win',step.get('win'));print('round keys',list(round_data),'step keys',list(step))
