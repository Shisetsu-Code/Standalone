"""Finish a recorded JSON-RPC demo round through observed server nextAction values."""
from rpc_hotrocket import RPC
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--policy',choices=['collect','gamble_once'],default='collect');p.add_argument('--start-feature',choices=['freespin_buy','high_freespin_buy']);a=p.parse_args();rpc=RPC();r=rpc.data['last_response']['result'];gambled=False
 if a.start_feature:
  assert r['final'] is True,'Unresolved prior round';r=rpc.call(a.start_feature)
 for i in range(500):
  if r.get('final') is True:
   g=r.get('resp',{}).get('engine',{}).get('gamestate',{});print('Round final; balance',r.get('balance'),'resp_win',r.get('resp',{}).get('win'),'totalWinnings',g.get('totalWinnings'),'free_win',g.get('freespinWinnings'),'steps',i,flush=True);break
  g=r.get('resp',{}).get('engine',{}).get('gamestate',{});next_action=g.get('triggeringDetails',{}).get('nextAction');choice=None
  if isinstance(next_action,list) and set(next_action)=={'gamble','collect'}:
   choice=2 if a.policy=='gamble_once' and not gambled else 1;gambled=gambled or choice==2
  elif next_action not in ['freespin','respin','jackpot','bonus','cascade']:raise RuntimeError('Unknown next action; round retained for review')
  r=rpc.call(choice=choice)
 else:raise RuntimeError('Continuation limit; no new round allowed')
