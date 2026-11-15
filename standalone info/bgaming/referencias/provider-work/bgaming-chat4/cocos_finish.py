"""Follow observed Cocos expected-step states with explicit source-backed request shapes."""
import json
from cocos_rpc import CocosRPC
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--start-bid',type=int,choices=[2,3]);p.add_argument('--policy',choices=['collect','gamble_once'],default='collect');p.add_argument('--repeat-for-choice',action='store_true');a=p.parse_args();rpc=CocosRPC();r=rpc.h.last;gambled=False;seen=set();stage=None
 if a.start_bid is not None:
  assert r.get('final') is True
  if not a.repeat_for_choice:
   ready=True
   for e in rpc.h.raw_events:
    if e['request']['method']!='play':continue
    if ready and e['request']['params']['req'].get('bid')==a.start_bid:raise RuntimeError('Bid already started; no duplicate purchase')
    ready=e['response'].get('result',{}).get('final',False)
  product=next(p for p in rpc.h.metadata['products'] if p['bid']==a.start_bid);r=rpc.call(dict(bet=rpc.bet,bet_type='bet',bid=a.start_bid,purchased_feature=product['purchased_feature']))
 for iteration in range(500):
  if r.get('final') is True:
   resp=r['resp'];win=resp.get('round',{}).get('win') or resp.get('step',{}).get('win') or '0';print('Cocos round final; balance',r['balance'],'win',win,'steps',iteration,'gamble_taken',gambled,flush=True);break
  resp=r.get('resp',{});step=resp.get('step',{});expected=[str(x.get('esmid','')).upper() for x in step.get('er',[])];req=dict(bet=rpc.bet,bet_type='bet')
  if any('RISK' in x for x in expected):
   decision='yes' if a.policy=='gamble_once' and not gambled else 'no';gambled=gambled or decision=='yes';req['custom_field']={'fid':{'a':decision}}
  elif expected and all(x.startswith(('FS1_','FS2_')) for x in expected):
   layout=step['ff'][0]['f'] if step.get('ff') and step['ff'][0].get('f') else step.get('f');signature=(tuple(expected),json.dumps(layout,sort_keys=True))
   if stage!=signature:seen=set();stage=signature
   if isinstance(step.get('fid'),dict) and 'x' in step['fid'] and 'y' in step['fid']:seen.add((step['fid']['x'],step['fid']['y']))
   cd=step.get('cd',{})
   if isinstance(cd,str):cd=json.loads(cd)
   for cell in cd.get('fe',[]):
    if 'x' in cell and 'y' in cell:seen.add((cell['x'],cell['y']))
   candidates=[(x,y) for x,col in enumerate(layout) for y,cell in enumerate(col) if cell.get('e')==18 and (x,y) not in seen]
   if not candidates:raise RuntimeError('No source-verified hidden cell available; inspect retained state')
   x,y=candidates[0];seen.add((x,y));req.update(bid=resp['round']['bet']['id'],custom_field={'fid':{'x':x,'y':y}})
  else:raise RuntimeError('Unknown Cocos expected-step state; no input sent')
  r=rpc.call(req)
 else:raise RuntimeError('Cocos continuation limit; state retained')
