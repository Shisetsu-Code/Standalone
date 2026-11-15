"""Native public-client wire format and validated Nolimit round contracts."""
from decimal import Decimal,ROUND_DOWN
import hashlib
import json
import re
import struct
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit

PROTOCOL='@nolimitcity/game-communication@0.4.1'
EXTRA_FIELDS={code:'playExtraSpin' for code in ('SixFeetUnder','GatorHunters2','Outsourced2','SoakedBySeamen','CatfishHunters','DuckHuntersHappyHour','PunkRocker3','Supersized','TombstoneBegins','DasxBoot2','Bizarre','GatorHunters','FlightMode','KillEmAll','Seamen','DuckHunters','HighwayToHell')}
EXTRA_FIELDS.update(DingDongDeath='playerSelectedExtraSpin',TrueGrit2='extraSpin',Disorder='playerSelectedExtraSpin',GoldenShower='playerSelectedExtraSpin',DeadMenWalking='playerSelectedExtraSpin')


def rc4_hex(key,text):
    key=key.encode('utf8');state=list(range(256));j=0
    for i in range(256):
        j=(j+state[i]+key[i%len(key)])%256;state[i],state[j]=state[j],state[i]
    i=j=0;out=[]
    for value in text.encode('utf8'):
        i=(i+1)%256;j=(j+state[i])%256;state[i],state[j]=state[j],state[i]
        out.append(value^state[(state[i]+state[j])%256])
    return bytes(out).hex()


def lzw_decode(text):
    if not text.startswith('lzw:'):return text
    raw=text[4:].encode('utf-16-le',errors='surrogatepass')
    codes=struct.unpack('<'+'H'*(len(raw)//2),raw)
    if not codes:raise ValueError('empty_lzw_frame')
    table={};previous=letter=chr(codes[0]);result=[previous];index=256
    for code in codes[1:]:
        entry=chr(code) if code<256 else table.get(code,previous+letter)
        result.append(entry);letter=entry[0];table[index]=previous+letter;index+=1;previous=entry
    return ''.join(result)


def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.search(r'(?:extplayerkey|playerconnect|sessionid|sessionkey|token|authorization|playerid|transportkey)$',k,re.I) else redact(v)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,str) and value.startswith(('https://','wss://')):
        url=urlsplit(value)
        query=[(k,'[REDACTED]' if k.lower() in ('data','key','token','session') else v) for k,v in parse_qsl(url.query,keep_blank_values=True)]
        return urlunsplit((url.scheme,url.netloc,url.path,urlencode(query),url.fragment))
    return value


def controls(init):
    game=init['game'];published=game.get('featureBuyTimesBetValue') or []
    if isinstance(init.get('allowedFeatureBets'),dict):
        result=[]
        for mode in init.get('allowedGameModes',[]):
            scoped=dict(init,allowedFeatureBets=init['allowedFeatureBets'].get(mode,[]),game=dict(game,featureBuyTimesBetValue=game.get('featureBuyTimesBetValueAll',{}).get(mode,[])))
            if mode!=game.get('playedCapMode'):
                result.append({'control_id':mode+'+NORMAL_PLAY','feature_name':None,'game_mode':mode,'type':'GAME_MODE','multiplier':'1'})
            for control in controls(scoped):result.append(dict(control,control_id=mode+'+'+control['control_id'],game_mode=mode))
        return result
    allowed=set(init.get('allowedFeatureBets',init.get('allowedGameFeatures',[])))
    features=[f for f in published if f['name'] in allowed and f.get('type')!='SIDE_BET']
    result=[{'control_id':f['name'],'feature_name':f['name'],'type':f['type'],'multiplier':str(f['price'])} for f in features]
    contexts={'NORMAL_PLAY':Decimal(1),**{f['name']:Decimal(str(f['price'])) for f in features}}
    allowed_side=set(init.get('allowedGameFeatures') or [])
    for context,multiplier in contexts.items():
        for name,cost in (game.get('sideBetCosts',{}).get(context) or {}).items():
            price=Decimal(str(cost))
            if name not in allowed_side or price<0:continue
            result.append({'control_id':context+'+'+name,'feature_name':None if context=='NORMAL_PLAY' else context,'side_name':name,
                'context':context,'type':'SIDE_BET','multiplier':str(multiplier+price),'side_multiplier':str(price)})
    if len({r['control_id'] for r in result})!=len(result):raise ValueError('duplicate_published_controls')
    return result


def choice_point(game,game_code):
    mode=game.get('nextMode')
    if game_code=='BookOfShadows' and mode=='FREESPIN_PICK':
        options=['NO'] if game.get('playerChoseRedrawSymbol') or game.get('mode')=='FREESPIN_PICK' else ['NO','REDRAW']
        family={'mode':mode,'interaction':'selectedRedraw','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':options,'published_costs':{'REDRAW':'0'}}
    picks=None
    if game_code=='SanQuentin2' and mode=='FREESPIN_SETUP1':picks=['1','2']
    if game_code=='Beheaded' and mode=='SUPER_FREESPIN_END':picks=['1','2']
    if game_code=='BrickSnake2000' and mode=='GAMBLE_FIFTY_FIFTY':picks=['0','1']
    if game_code=='Loner' and mode=='FEATURE_TICK_TICK_BOOM':picks=['1','2','3']
    if game_code=='DDay' and mode=='FS_PICK':picks=[str(i) for i,value in enumerate(game['fsPicks']) if value<0]
    if game_code in ('BuffaloHunter','Deadwood','DragonTribe','EastVsWest','ElPaso','Infectious5','MiseryMining') and mode=='FREESPIN_PICK':picks=['1','2']
    if game_code=='GaelicGold' and mode=='FREESPIN_PICKS':picks=[str(i) for i,value in enumerate(game['pickedIndexesAfter']) if not value]
    if picks:
        family={'mode':mode,'interaction':'selectedIndex','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':picks,'default':picks[0],'published_costs':{o:'0' for o in picks}}
    if mode=='FREESPIN_PICK' and game_code=='TsarWars':
        family={'mode':mode,'interaction':'selectedIndex','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':['1','2','3'],'default':'1','published_costs':{'1':'0','2':'0','3':'0'}}
    if mode=='GAMBLE' and game_code=='BookOfShadows':
        available=game.get('gambleOptions',{});options=['NO']
        if game.get('numberOfGamblesDone',0)<game.get('numberOfGamblesAllowed',0):
            if Decimal(str(available.get('FiftyFifty',0)))>0:options+=['RED','BLACK']
            if Decimal(str(available.get('FeatureWin',0)))>0:options.append('FEATURE')
        family={'mode':mode,'interaction':'gambleOption','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':options,'published_costs':{o:'0' for o in options if o!='NO'}}
    if mode=='UPGRADE_BET' and game_code=='Outsourced':
        cost=Decimal(str(game['upgradeBetCost']))
        if Decimal(str(game['accumulatedRoundWin']))<cost:return None
        family={'mode':mode,'interaction':'playUpgradeBet','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':['NO','YES'],'published_costs':{'YES':str(cost)}}
    if mode!='EXTRA_SPIN':return None
    if game_code=='Tanked3':
        costs={k:v for k,v in game.get('extraSpinCostMap',{}).items() if Decimal(str(v))>0}
        family={'mode':mode,'interaction':'playExtraSpin','game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':['NO']+list(costs),'published_costs':costs}
    if game_code in EXTRA_FIELDS:
        field=EXTRA_FIELDS[game_code]
        family={'mode':mode,'interaction':field,'game':game_code}
        return {'node':hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16],'family':family,'options':['NO','YES'],'published_costs':{'YES':str(game['extraSpinCost'])}}
    if game_code!='DuckHunters2':raise ValueError('unverified_extra_spin_contract:'+game_code)
    costs=game.get('extraSpinCostMap') or {};options=['NO']
    if 'HALF' in costs and Decimal(str(costs['HALF']))>=0:options.append('HALF')
    if 'SAME' in costs and Decimal(str(costs['SAME']))>=0 and Decimal(str(game['accumulatedRoundWin']))>=Decimal(str(costs['SAME'])):options.append('SAME')
    family={'mode':mode,'interaction':'playExtraSpin','game':game_code}
    node=hashlib.sha256(json.dumps(family,sort_keys=True).encode()).hexdigest()[:16]
    return {'node':node,'family':family,'options':options,'published_costs':costs}


def _continuation(game,game_code,selected=None):
    mode=game.get('nextMode')
    if mode=='NORMAL':return None
    point=choice_point(game,game_code)
    if point:
        selected=selected or point.get('default','NO')
        if selected not in point['options']:raise ValueError('disabled_or_unpublished_extra_spin_option')
        if point['family']['interaction']=='selectedIndex':return {'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':int(selected) if game_code=='Infectious5' else selected}}
        if point['family']['interaction']=='selectedRedraw':
            content={'type':'zeroBet','bet':'0.00'}
            if selected=='REDRAW':content['playerInteraction']={'selectedRedraw':'2'}
            elif not game.get('wasFeatureBuy'):content['playerInteraction']={'selectedIndex':str(int(game['playedRowsInBase'])-2)}
            return content
        if mode=='GAMBLE':
            if selected=='NO':return {'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':True}}
            option,selection={'RED':('0','1'),'BLACK':('0','2'),'FEATURE':('1','-1')}[selected]
            return {'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':False,'gambleOption':option,'gambleSelection':selection}}
        interaction={'playUpgradeBet':int(selected=='YES')} if mode=='UPGRADE_BET' else {'playExtraSpin':selected}
        if game_code in EXTRA_FIELDS:interaction={point['family']['interaction']:selected.lower()}
        if game_code=='Disorder':interaction={'playerSelectedExtraSpin':str(int(selected=='YES'))}
        if game_code in ('GoldenShower','DeadMenWalking'):interaction={'playerSelectedExtraSpin':int(selected=='YES')}
        if game_code=='Tanked3':interaction={'playExtraSpin':'nonono' if selected=='NO' else selected}
        return {'type':'zeroBet','bet':'0.00','playerInteraction':interaction}
    if mode=='EXTRA_SPIN_CHECK' and game_code in ('GoldenShower','DeadMenWalking','Disorder','Tanked3'):return {'type':'zeroBet','bet':'0.00'}
    if game_code=='SanQuentin2' and mode=='FREESPIN_SETUP2':return {'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':'1'}}
    if game_code=='Loner' and mode in ('FEATURE_PIN_THE_WIN','FEATURE_SHOOT_SHOOT_DUCK'):return {'type':'zeroBet','bet':'0.00'}
    if (game_code,mode) in (('BonusBunnies','BONUS_GAME'),('ImmortalFruits','BONUS_WHEEL')):return {'type':'zeroBet','bet':'0.00'}
    if (game_code,mode) in (('FireInTheHole','BONUS'),('EvilGoblins','DOUBLE_BOMB')):return {'type':'zeroBet','bet':'0.00'}
    if game_code=='MiseryMining' and mode in ('BONUS','BONUS_COOL','BONUS_SUPER'):return {'type':'zeroBet','bet':'0.00'}
    if game_code=='TrueGrit2' and mode in ('EXTRA_SPIN_NORMAL','EXTRA_SPIN_FS','EXTRA_SPIN_SFS','EXTRA_SPIN_SDFS'):return {'type':'zeroBet','bet':'0.00'}
    if mode=='DESTRUCTION' and game_code=='TsarWars':return {'type':'zeroBet','bet':'0.00'}
    if mode=='CAPWIN_GAME' and game_code=='HomeOfTheBrave':return {'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':'1'}}
    if mode=='UPGRADE_BET' and game_code=='Outsourced':return {'type':'zeroBet','bet':'0.00'}
    if mode=='GAMBLE':return {'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':True}}
    if mode and not re.search('PICK|SELECT|CHOICE|EXTRA|GAMBLE',mode) and re.search('FREESPIN|RESPIN|AVALANCHE',mode):return {'type':'zeroBet','bet':'0.00'}
    raise ValueError('unknown_continuation_mode:'+str(mode))


def continuation(game,game_code,selected=None):
    content=_continuation(game,game_code,selected)
    if content and game_code=='KennethMustDie':content.setdefault('playerInteraction',{})['gameMode']=game['playedCapMode']
    return content


def native_win(responses,game_code=None):
    games=[r['game'] for r in responses if isinstance(r.get('game'),dict)]
    if not games or games[-1].get('nextMode')!='NORMAL':raise ValueError('round_not_closed')
    if 'accumulatedRoundWin' not in games[-1]:
        if game_code=='KitchenDramaSushiMania' and 'totalRoundWin' in games[-1]:return Decimal(str(games[-1]['totalRoundWin']))
        raise ValueError('native_payout_field_unknown')
    return Decimal(str(games[-1]['accumulatedRoundWin']))


def check_wallet(before,cost,win,after):
    before,cost,win,after=map(lambda x:Decimal(str(x)),(before,cost,win,after))
    raw=before-cost+win;expected=raw.quantize(Decimal('.01'),rounding=ROUND_DOWN)
    if expected!=after:raise ValueError('wallet_mismatch:expected='+str(expected)+',actual='+str(after))
    return {'cost':str(cost),'win':str(win),'settled_win':str(after-before+cost),'rounding_adjustment':str(raw-after),'settlement_rule':'truncate_final_balance_2dp','balance_after':str(after),'wallet_check':'match'}
