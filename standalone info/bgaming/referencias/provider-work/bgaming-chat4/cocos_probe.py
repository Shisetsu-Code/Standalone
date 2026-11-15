"""Verify Cocos bid:0 on the existing fresh FUN QA session; never repeat a play."""
import json,time,urllib.request,copy
from types import SimpleNamespace
from urllib.parse import urlsplit
from run_demo_qa import ROOT,PRIVATE,save,now
from hyperhive_adapter import Hyperhive
from analyze import Sanitizer
if __name__=='__main__':
 gid='RedAndHotChilli';path=PRIVATE/'hyperhive'/(gid+'.session.json');s=json.loads(path.read_text(encoding='utf8'));assert s['fresh_demo'] and s['status']=='received' and s['last_result']['currency']=='FUN' and s['last_result']['state'] is None
 assert not any(e['request']['method']=='play' for e in s['events']),'Existing play must be reviewed, never repeated'
 state=json.loads((ROOT/'run-state.json').read_text(encoding='utf8'));assert state['active_game'] is None;time.sleep(max(0,60-(time.time()-state['last_launch_epoch'])));state['last_launch_epoch']=time.time();state['active_game']=gid;state['updated_at']=now();save(ROOT/'run-state.json',state)
 u=urlsplit(s['endpoint']);origin=u.scheme+'://'+u.netloc;parent=SimpleNamespace(game={'game_id':gid},page=origin+'/hyperhive',opener=urllib.request.build_opener(),events=[],clean=Sanitizer(),bootstrap={},money_checks=[])
 h=Hyperhive(parent,{'play_token':s['token']});h.raw_events=s['events'];h.initial=s['initial'] or s['events'][0]['response'];h.last=s['last_result'];h.metadata=json.loads((ROOT/'protocols/RedAndHotChilli.cocos.json').read_text(encoding='utf8'));bet=min(h.last['config']['bet_limits']);before=h.last['balance'];response=h.request('play',dict(bet=bet,bet_type='bet',bid=0));result=response['result'];native=result.get('resp',{})
 print('Cocos normal final',result.get('final'),'before',before,'balance',result.get('balance'),'resp keys',list(native));print('round keys',list(native.get('round',{})),'step keys',list(native.get('step',{})));print('native bet',native.get('round',{}).get('bet'),'round win',native.get('round',{}).get('win'),'step win',native.get('step',{}).get('win'))
 save(PRIVATE/'cocos'/('RedAndHotChilli.normal.json'),dict(before_balance_native=before,request=h.raw_events[-1]['request'],response=response))
 if result.get('final') is True:state['active_game']=None
 state['updated_at']=now();save(ROOT/'run-state.json',state)
