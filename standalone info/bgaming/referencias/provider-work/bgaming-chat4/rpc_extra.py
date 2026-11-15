"""Source-proved custom RPC families. No network, token, or session creation here.

The Hyper client supplies request('play', req), including its current state_lock.
All bets, prices, wins and wallet values remain in native FUN subunits.
"""
import hashlib
import re
from fractions import Fraction


def metadata(source, allowed):
 def require(*tokens):
  if not all(t in source for t in tokens):
   raise ValueError('Custom RPC source contract incomplete')
 if 'purchaseFeaturesConfig:[{id:"chance"' in source:
  require('custom_field:null==i?void 0:i.id,purchased_feature:null==i?void 0:i.type',
          'sendPlay({bet:this.wrapperModel.bet.base', 'result.resp.roundData',
          'get bet(){const e=$r(this._bet,this.buyChanceMultiplier);return{base:this._bet,value:e,',
          'id:"chance",type:"buy_chance",configFeatureType:"buy_chance",betPriceMultiplier:2',
          'id:"buy_random",type:"buy_bonus",configFeatureType:"buy_bonus",price:100',
          'id:"buy_max",type:"buy_bonus",configFeatureType:"buy_bonus",price:300')
  family='recycle-riches'
  products=[('chance','buy_chance','2',{'custom_field':'chance','purchased_feature':'buy_chance'}),('buy_random','buy_bonus','100',{'custom_field':'buy_random','purchased_feature':'buy_bonus'}),('buy_max','buy_bonus','300',{'custom_field':'buy_max','purchased_feature':'buy_bonus'})]
  evidence='Native bet.base; purchaseFeaturesConfig IDs, prices and betPriceMultiplier; custom_field=id, purchased_feature=type; cumulative resp.roundData.roundWin; ordinary sendPlay for bonus continuations.'
 elif 'bonus_multiplier_type:"freeSpinRandom"' in source:
  require('goldenBetMulti:1.5','const e=zb(),t=100*e.bet,n=200*e.bet',
          'bet:e.bet,purchased_feature:"buy_bonus",bonus_multiplier_type:"freeSpin"',
          'bet:e.bet,purchased_feature:"buy_bonus",bonus_multiplier_type:"freeSpinRandom"',
          'bet_type:t?"freebet":"bet"', 'e.total+=n.winResult.multipliedTotalWin',
          't.total+e.commonGame.totalWin', 'e.stepCount>t||')
  family='blackbeards-bounty'
  products=[('buy_chance','buy_chance','1.5',{'bet_type':'bet','purchased_feature':'buy_chance'}),('freeSpin','buy_bonus','100',{'purchased_feature':'buy_bonus','bonus_multiplier_type':'freeSpin'}),('freeSpinRandom','buy_bonus','200',{'purchased_feature':'buy_bonus','bonus_multiplier_type':'freeSpinRandom'})]
  evidence='Native bet; goldenBetMulti=1.5; freeSpin=100x and freeSpinRandom=200x; same-game continuation sends bet_type=bet without purchase; commonGame.totalWin plus Xy cumulative multipliedTotalWin through roundStep.'
 elif 'bet_type:"betting",action:"wheel"' in source:
  require('bet_type:"betting",action:"spin"','bet_type:"betting",action:"bonus"',
          'bet_type:"betting",purchased_feature:"buy_chance"','bet_type:"betting",purchased_feature:"buy_bonus"',
          'this.isHistoryBuyBonus?this.statusBar.updateBalance(i-100*s+e)',
          'this.isAnteSpinActive?this.statusBar.updateBalance(i-1.4*s+e)',
          'result.resp.game.totalWin','"BONUS"===r||"WHEEL"===r')
  family='blazing-firepots'
  products=[('buy_chance','buy_chance','1.4',{'bet_type':'betting','purchased_feature':'buy_chance'}),('buy_bonus','buy_bonus','100',{'bet_type':'betting','purchased_feature':'buy_bonus'})]
  evidence='Native betting request with action=spin; purchases 1.4x/100x shown by wallet replay formula; nextAction WHEEL/BONUS maps to wheel/bonus; cumulative resp.game.totalWin.'
 elif 'const n="buybonus",s="buybonus"' in source:
  require('req:{bet:l,action:r,bet_type:o}', '"BASE"===e?r="spin"',
          '"FREEGAME"===e&&(r="freespin")', 'let t,s,a,r="",o="bet"',
          'action:n,id:s,purchased_feature:"buy_bonus"', 'const ha=20,ua=100',
          'formatWin(da*ua)', 'Fo.totalWin=Number(t.results.win.total)/vr')
  family='jungle-queen'
  products=[('buybonus','buy_bonus','100',{'action':'buybonus','id':'buybonus','purchased_feature':'buy_bonus'})]
  evidence='Native FUN bet from UI currency multiplier; explicit action/id buybonus; ua=100 purchase price; normal spin and FREEGAME freespin actions; each response results.win.total is the current spin payout (state.totalWin is separately accumulated).'
 elif 'class rl{toJson(){return{bet:this.bet,bet_type:this.betType,purchased_feature:this.purchasedFeature}}}' in source:
  require('this.roundBase=1,this.roundBaseForBet=1,this.fsMultiplier=50',
          'r.bet=this._session.slotSession.currentBet.bet/this._session.slotSession.currentBet.roundBaseForBet,r.betType="default"',
          'r.purchasedFeature=""==this._session.slotSession.BonusType?null:this._session.slotSession.BonusType',
          'this._session.slotSession.BonusType=""', 'this._slotSession.BonusType="buy_bonus"',
          'betLimits:e.bet_limits?Array.from(e.bet_limits)',
          'n.totalWin=i.totalWin/this.session.slotSession.bet.subunits',
          'this._stateMachine.curResponse.freeSpinsInfo.totalWin-this._stateMachine.curResponse.totalWin')
  family='sugar-mix'
  products=[('buy_bonus','buy_bonus','50',{'bet_type':'default','purchased_feature':'buy_bonus'})]
  evidence='Native config.bet_limits copied to bets; roundBaseForBet=1; req bet_type=default, purchased_feature=null normally; explicit buy_bonus UI and fsMultiplier=50; feature resets after each response; resultState.totalWin current payout versus separately accumulated freeSpinsInfo.totalWin.'
 elif 'const Iv={buy_chance:1.4,buy_bonus:100,buy_bonus_and_chance:250}' in source:
  require('machineId:"6"','bets:n.result.config.bet_limits.map((e=>e/this.params.maxLines))',
          'req:{bet:e.bet*this.params.maxLines,machineId:e.spinParams?.machineId?parseInt(e.spinParams.machineId,10):0',
          't.machineId=this._session.slotSession.GameId.toString()',
          'req:{bet:e.params.bet*this.params.maxLines,machineId:parseInt(e.params.machineId,10),purchased_feature:e.params.feature}',
          'e||"buy_chance"!==this._buyBonusStore.state?.feature?this._spinResponseProvider.doRequest(e):this._buyBonusResponseProvider.doRequest(e)',
          'machineState:s.result.resp', 'n.totalWin=t.totalWin??0')
  family='treasure-explorer'
  products=[(f,f,p,{'machineId':6,'purchased_feature':f}) for f,p in [('buy_chance','1.4'),('buy_bonus','100'),('buy_bonus_and_chance','250')]]
  evidence='Game machineId=6; config total bets divided by maxLines only inside UI, then multiplied back in wire; exact Iv source prices 1.4/100/250; chance selects purchase provider on a paid spin; normal continuations use plain machineId=6; resp.totalWin current payout separate from freeSpinsInfo.'
 elif 'custom_field:"custom_value",fe_exponent:this.globalState.feBetExponent' in source:
  require('req:{bet:e,bet_type:s,custom_field:"custom_value",fe_exponent:this.globalState.feBetExponent}',
          '"freebet":"default"', 'bet:10,reels:3',
          'this.determine_exponent=(t,e)=>{let i=0;',
          'this.calculate_exponent=(t,e)=>{let i=t/e.subunits,s=i.toString().includes(".")?i.toString().split(".")[1].length+1:0;',
          'this.showWin(s.totalWin/h.Config.bet*t,!0)', 'const t=i.resp?.super_spin.bet')
  if 'purchased_feature' in source:raise ValueError('Zeus purchase contract changed')
  family='zeus-goes-wild';products=[]
  evidence='Native request bet unchanged, bet_type=default, custom_field=custom_value, fe_exponent from decimal places of full bet_limits; no client purchase wire. Source fixed Config.bet=10; payout shown as final stage.totalWin/10 * super_spin.bet, exact rational conversion to native wallet.'
 elif 'window.console.log("robospin v1.0.5")' in source:
  require('i.command==="spin"&&(i.command="play",a=i.options.req,a.bet=i.options.bet||s.data.bet',
          'available_bets:a.bet_limits,default_bet:a.default_bet',
          'function lr(i){i.outcome=i.resp', 'const r=e.outcome&&e.outcome.win',
          'super.spinRequest({req:{traits_to_win:s.all.traitsToWin.value,selected_traits:{hat:',
          'if(e.isLeftSelected)return"left";if(e.isRightSelected)return"right"',
          'const fi=6,cr=[[1,1,1.96],[2,1,1.3],[2,2,3.92]',
          '[6,1,NaN],[6,2,1.1],[6,3,1.49],[6,4,2.85],[6,5,8.95],[6,6,62.72]')
  family='robospin';keys=['hat','ears','arms','head','body','bg'];products=[]
  for count in range(1,7):
   for threshold in range(2 if count==6 else 1,count+1):
    products.append((f'traits_{count}_need_{threshold}',None,'1',{'traits_to_win':threshold,'selected_traits':dict.fromkeys(keys[:count],'left')}))
  evidence='Robot-specific req selected_traits with literal left/right (unselected undefined keys omitted by JSON.stringify), 1..6 selected and source payout table thresholds excluding NaN six/one. Canonical all-left subset per count/threshold exercises each payout setting; not exhaustive trait identities/sides. Native available_bets and resp.win. Shared generic buy UI is not a robot product registry.'
 elif 'this["mGameName"]=\'kots_\',this["mCoefBonus"]=0x78' in source:
  require('class BSPOSTBGManager',
          '_0x42528f["req"]["bet"]=Math["round"](Player["getTotalBetValue"]()*Player[\'getDivisorAfterPoint\']())["toString"]()',
          '_0x42528f["req"]["purchased_feature"]="buy_bonus"',
          'this["mRollCB"](_0x51fe42["step"],_0x78d84,_0x357664)',
          '_0x24eef8["_checkRollOnWin"](_0xef6a4a[\'c\'],_0x52f076,_0x18a04a,eConnectionType["POST"],_0xef6a4a["win"])')
  family='keepers-secret';products=[('buy_bonus','buy_bonus','120',{'purchased_feature':'buy_bonus'})]
  evidence='Statically decoded official Game/BS_lib string tables; Game mCoefBonus=0x78 (120); native bet serialized as decimal string; bought request adds only purchased_feature=buy_bonus; client resets buy selection after first response; roll callback receives resp.step and uses its win per response. No source JavaScript executed.'
 elif "eBetsIDs={'DEFAULT':0x0,'SHOP':0x1,'SHOP_2':0x2,'SHOP_3':0x3,'ANTE':0x4}" in source:
  import json
  require('_0x577c5b["req"][\'bid\']=Player["getCurBetID"]()',
          '_0x577c5b["req"]["purchased_feature"]="buy_bonus"',
          'this[\'mRollCB\'](_0x5bf425[\'step\'],_0x412451,_0x5c78ab)',
          '_0x5053d9["modeType"],_0x5f3916["win"])',
          'Math["round"](Player["getTotalBetValue"]()*Player[\'getDivisorAfterPoint\']())[\'toString\']()')
  starts=list(re.finditer(r'\{\s*"bet_slots"\s*:',source))
  if len(starts)!=1:raise ValueError('Grand Patron static bet_slots registry missing/ambiguous')
  registry=json.JSONDecoder().raw_decode(source[starts[0].start():])[0]['bet_slots']
  if [(p['id'],p['rmid']) for p in registry]!=[(0,'DEF'),(1,'SHOP'),(2,'SHOP2'),(3,'SHOP3'),(4,'ANTE')]:raise ValueError('Grand Patron registry IDs changed')
  family='grand-patron';products=[]
  for p in registry[1:]:
   feature='buy_chance' if p['type']=='ante' else 'buy_bonus'
   req={'bid':p['id']}
   if p['type']=='bb':req['purchased_feature']='buy_bonus'
   products.append((p['rmid'],feature,p['cmx'],req))
  evidence='Statically decoded official game enum DEFAULT0 SHOP1 SHOP_2=2 SHOP_3=3 ANTE4; native decimal-string bet plus bid on EVERY request; purchase flag on first bought request only; exact official bets_data bet_slots cmx factors100/250/1000/1.3; curbid retained until final; resp.step.win per response.'
 elif 'title:"Big Bucks Saloon"' in source:
  require('var a={req:{bet:s.A.data.bet}}',
          'initBalance(t){this.buyBonusMultiplier=120,super.initBalance(t)}',
          'buyBonus(){this.spin(!0,{purchased_feature:"buy_bonus"})',
          's.A.data.initialAvailableBets=i.bet_limits',
          'this.replayPostSpinBalanse+Number(t.result.resp.round.win)',
          'if(s.A.data.infoLine.freespinsLeft<0)return;this.spin()')
  family='big-bucks-saloon';products=[('buy_bonus','buy_bonus','120',{'purchased_feature':'buy_bonus'})]
  evidence='Official dynamically selected versioned Big Bucks bundle; normal req native bet only; exact subclass buyBonusMultiplier=120 and buy_bonus request; native config bet_limits; automatic ordinary spin continuation; final cumulative resp.round.win used in replay wallet formula (Number accepts numeric strings).'
 elif 'feature_buy:e,purchased_feature:r,bonus_type:this.globalState.bonusType,buyBonusModeMultiplier:o' in source:
  require('this.buyBonusModeMultiplier1=100,this.buyBonusModeMultiplier2=300,this.businessmanModeMultiplier1=3,this.businessmanModeMultiplier2=10,this.businessmanModeMultiplier3=800',
          'case h.ante_0:this.globalState.selectedBusinesssmanModeMultiplier=this.globalState.businessmanModeMultiplier2',
          'case h.ante_1:this.globalState.selectedBusinesssmanModeMultiplier=this.globalState.businessmanModeMultiplier1',
          'case h.ante_2:this.globalState.selectedBusinesssmanModeMultiplier=this.globalState.businessmanModeMultiplier3',
          'this.pointerdownHandler("1","anubis")','this.pointerdownHandler("0","hades")',
          'this.text_freespins_amount.container.visible&&(r=null,e=null)',
          'bet:10,reels:5','this.showWin(s.totalWin/h.Config.bet*t,!0)')
  family='clash-gods';products=[]
  for name,feature,factor,multiplier in [('normal',None,'1',1),('ante_0','buy_chance','10',1),('ante_1','buy_chance','3',1),('ante_2','buy_chance','800',1),('buy_bonus','buy_bonus','100',100),('super_buy_bonus','buy_bonus','300',300)]:
   for choice in ('hades','anubis'):
    products.append((name+'_'+choice,feature,factor,{'bet_type':'default','feature_buy':None if name=='normal' else name,'purchased_feature':feature,'buyBonusModeMultiplier':multiplier}))
  evidence='Explicit feature_buy identifiers, buy multipliers100/300, ante enum mapping ante_0=10 ante_1=3 ante_2=800; UI cards choose bonus_type string0 Hades or1 Anubis after trigger; continuations clear feature_buy/purchased_feature and multiplier1. Native bet unchanged; Config.bet10 normalized cumulative stage.totalWin converted exactly to native via response.bet.'
 elif 'playBonusEnd:async()=>{try{const i=' in source:
  require('t.result.custom_params=bV()', 'function bV(){return{win:!1',
          'instant_bonus_game_multiplier:"80",init_slot:wV(),ante_bet_multiplier:"2.0"',
          'OT=We(5)', '...n?{instant_bonus_game:n}:{},...n?{purchased_feature:"buy_bonus"}:{},...e?{ante_bet:!0}:{},...t?{wild_bet:!0}:{}',
          '$t=(i,e=2,t=2,n=-1)=>{const s=Number(i/10**e);return wo(s,t)},yr=(i,e=2)=>Number(Number(i*10**e).toFixed(0))',
          'kb=hs([li,Pi],([i,e])=>e===null?0:yr(i,e))',
          'Bi.set(y),Ik(y),y&&oi.set(!1)', 'oi.set(y),Mk(y),y&&Bi.set(!1)',
          'let h=l.resp.win_amount;const u=await H0.playBonus()',
          'bonus_game:"WILD_DICES"', 'bonus_game:"WILD_DICES_FINISH"',
          'await H0.playBonusEnd()', 'jl.set(Te(jl)+Te(d0))')
  family='aztecs-claw';products=[('ante_bet','buy_chance','2',{'bet_type':'bet','ante_bet':True}),('wild_bet','buy_bonus_and_chance','5',{'bet_type':'bet','wild_bet':True}),('instant_bonus','buy_bonus','80',{'bet_type':'bet','instant_bonus_game':True,'purchased_feature':'buy_bonus'})]
  evidence='Native currency formatting $t is reversed by yr before wire bet; bV injected client config proves ante2/buy80, OT5 wild multiplier; toggles mutually exclusive (no combined product). Exact instant_bonus_game boolean true. Trigger WILD_DICES invokes playBonus, response WILD_DICES_FINISH then explicit finish acknowledgment irrespective of middle final flag. Base win_amount + bonus win_amount, final acknowledgment adds no payout; UI adds stored bonus to base balance only after finish.'
 else:
  raise ValueError('No supported custom RPC source family')
 return dict(engine='rpc-extra',protocol='jsonrpc-rpc-extra',family=family,products=[dict(id=i,feature=f,factor=p,request=q) for i,f,p,q in products if f is None or f in allowed],source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence=evidence,unresolved=[],coverage_limit='Only explicit source-visible products. Global purchased_features is an availability filter, never a product registry. Live verification remains required.')


def plan(initial, meta):
 r=initial['result'];a=r['currency_attributes'];bets=r['config']['bet_limits']
 if r['currency']!='FUN' or a['subunits']!=100 or a['exponent']!=2 or r.get('state') is not None or r.get('freebets') or not bets or any(type(b) is not int or b<=0 for b in bets):
  raise ValueError('Unverified initial native FUN state')
 bet=min(bets);modes=[]
 defaults=[] if meta['family'] in ('robospin','clash-gods') else [dict(id='normal',factor='1',request={})]
 for p in defaults+meta['products']:
  cost=bet*Fraction(p['factor'])
  if cost.denominator!=1:raise ValueError('Fractional native product cost')
  mode=dict(name=p['id'],protocol='jsonrpc-rpc-extra',family=meta['family'],bet_native=bet,cost_native=int(cost),request=p['request'])
  if meta['family'] in ('zeus-goes-wild','clash-gods'):
   mode['fe_exponent']=max(a['exponent'],max(0 if b%100==0 else len(str(b%100).zfill(2).rstrip('0'))+1 for b in bets))
  if meta['family']=='clash-gods':mode['bonus_choice']='1' if p['id'].endswith('_anubis') else '0'
  modes.append(mode)
 return modes


def _request(mode, previous=None):
 req={'bet':mode['bet_native']};family=mode['family']
 if family=='aztecs-claw':
  req['bet_type']='bet'
  if previous is not None:
   bonus=previous['resp'].get('bonus_game')
   if bonus not in ('WILD_DICES','WILD_DICES_FINISH'):raise RuntimeError('Unknown Aztec bonus continuation')
   req['bonus_game']=bonus
 if family in ('keepers-secret','grand-patron'):req['bet']=str(mode['bet_native'])
 if family=='grand-patron':req['bid']=mode['request'].get('bid',0)
 if family=='robospin' and previous is not None:raise RuntimeError('Robot instant round unexpectedly open; no continuation sent')
 if family=='zeus-goes-wild':req.update(bet_type='default',custom_field='custom_value',fe_exponent=mode['fe_exponent'])
 if family=='treasure-explorer':req['machineId']=6
 if family=='sugar-mix':req.update(bet_type='default',purchased_feature=None)
 if family=='jungle-queen':
  req.update(action='spin',bet_type='bet')
  if previous is not None:
   if previous['resp']['state']['status'] not in ('FREESPINS_TRIGGER','FREESPINS'):raise RuntimeError('Unknown Jungle Queen continuation state')
   req['action']='freespin'
 if family=='blackbeards-bounty':req['bet_type']='bet'
 if family=='blazing-firepots':
  req['bet_type']='betting'
  action='SPIN' if previous is None else previous['resp'].get('nextAction')
  if action not in ('SPIN','WHEEL','BONUS'):raise RuntimeError('Unknown Firepots nextAction; no continuation sent')
  req['action']=action.lower()
 if previous is None and mode['request']:
  # Purchased rounds have their own explicit request shape (without action,
  # and Blackbeard purchases also omit bet_type in the native UI).
  req={'bet':str(mode['bet_native']) if family in ('keepers-secret','grand-patron') else mode['bet_native'],**mode['request']}
 if family=='clash-gods':
  req['fe_exponent']=mode['fe_exponent']
  if previous is not None:
   req.update(bet_type='default',feature_buy=None,purchased_feature=None,buyBonusModeMultiplier=1,bonus_type=mode['bonus_choice'])
 return req


def _money(value):
 if type(value) not in (int,float) or value<0:raise ValueError('Invalid native money')
 return Fraction(str(value))


def _win(result, family):
 resp=result['resp']
 if family=='aztecs-claw':return _money(resp['win_amount'])
 if family=='big-bucks-saloon':
  value=resp['round'].get('win',0)
  if type(value) is str:
   if not re.fullmatch(r'\d+(?:\.\d+)?',value):raise ValueError('Invalid Big Bucks native numeric-string win')
   return Fraction(value)
  return _money(value)
 if family in ('keepers-secret','grand-patron'):
  value=resp['step'].get('win',0)
  if isinstance(value,str):
   if not re.fullmatch(r'\d+',value):raise ValueError('Invalid native integer string payout')
   value=int(value)
  return _money(value)
 if family=='robospin':return _money(resp['win'])
 if family in ('zeus-goes-wild','clash-gods'):
  data=resp['super_spin'];return _money(data['round']['stages'][-1]['totalWin'])*_money(data['bet'])/10
 if family=='treasure-explorer':return _money(resp['totalWin'])
 if family=='sugar-mix':return _money(resp['resultState']['totalWin'])
 if family=='jungle-queen':
  value=resp['results']['win']['total']
  # Jungle's source uses Number(t.results.win.total), proving numeric
  # strings. Preserve the raw response and parse exactly, without floats.
  if type(value) is str:
   if not re.fullmatch(r'\d+(?:\.\d+)?',value):raise ValueError('Invalid Jungle native numeric-string win')
   return Fraction(value)
  return _money(value)
 if family=='recycle-riches':return _money(resp['roundData']['roundWin'])
 if family=='blazing-firepots':return _money(resp['game']['totalWin'])
 if family=='blackbeards-bounty':
  total=_money(resp['commonGame']['totalWin']);free=resp.get('freespinsGame')
  if free:
   step=0;limit=resp['roundStep']
   if type(limit) is not int or limit<0:raise ValueError('Invalid bonus roundStep')
   for event in free['data']:
    step+=event['type']=='INITIAL_FREE_SPIN'
    if step<=limit:total+=_money(event['winResult']['multipliedTotalWin'])
  return total
 raise ValueError('Unknown custom family')


def run(h, mode):
 if h.last.get('final') is False or (h.last.get('state') is not None and 'final' not in h.last):raise RuntimeError('Custom RPC round already open')
 before=_money(h.last['balance']);cost=mode['cost_native'];start=len(h.parent.events)
 if before<cost:return dict(mode=mode,status='insufficient_demo_balance')
 req=_request(mode);incremental=Fraction(0)
 for step in range(500):
  r=h.request('play',req)['result']
  if type(r.get('final')) is not bool or (not isinstance(r.get('resp'),dict) and not (mode['family']=='aztecs-claw' and step==2)):raise RuntimeError('Custom RPC final/resp missing; no retry')
  if mode['family']=='aztecs-claw':
   if step==0:
    incremental+=_win(r,mode['family'])
    if r['final']:break
    if r['resp'].get('bonus_game')!='WILD_DICES':raise RuntimeError('Unknown Aztec trigger; no continuation sent')
   elif step==1:
    if r['resp'].get('bonus_game')!='WILD_DICES_FINISH':raise RuntimeError('Unknown Aztec bonus result; no finish sent')
    incremental+=_win(r,mode['family'])
   elif step==2:
    if r['final'] is not True:raise RuntimeError('Aztec finish acknowledgment did not close round')
    break
   req=_request(mode,r)
   continue
  if mode['family'] in ('zeus-goes-wild','clash-gods') and r['resp']['super_spin']['bet']!=mode['bet_native']:raise RuntimeError('Normalized-stage native response bet mismatch')
  if mode['family'] in ('jungle-queen','sugar-mix','treasure-explorer','keepers-secret','grand-patron'):incremental+=_win(r,mode['family'])
  if r['final']:break
  req=_request(mode,r)
 else:raise RuntimeError('Custom RPC continuation limit')
 win=incremental if mode['family'] in ('jungle-queen','sugar-mix','treasure-explorer','keepers-secret','grand-patron','aztecs-claw') else _win(r,mode['family']);actual=_money(r['balance']);expected=before-cost+win;ok=expected==actual
 h.parent.money_checks.append(dict(kind='rpc_extra_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=r['balance'],ok=ok))
 if not ok:raise RuntimeError('Custom RPC native wallet mismatch; no next round sent')
 return dict(mode=mode,status='closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=r['balance'],final_state='final',win_ratio=[win.numerator,win.denominator],win_native=int(win) if win.denominator==1 else float(win))


def audit(initial,events,meta):
 modes=plan(initial,meta);balance=_money(initial['result']['balance']);checks=[];rounds=[];current=None;previous=None;incremental=Fraction(0)
 for index,event in enumerate(events):
  if event['request'].get('method')!='play':continue
  req=event['request']['params']['req'];r=event.get('response',{}).get('result')
  if current is None:
   matches=[m for m in modes if _request(m)==req]
   if not matches or (len(matches)!=1 and meta['family']!='clash-gods'):raise ValueError('Unrecognized source-proved custom request')
   current=dict(first_event=index,mode=matches[0],closed=False);rounds.append(current)
   if meta['family']=='clash-gods':current['candidate_modes']=matches
  elif req!=_request(current['mode'],previous):
   matches=[m for m in current.get('candidate_modes',[]) if _request(m,previous)==req]
   if len(matches)!=1:raise ValueError('Unrecognized custom continuation')
   current['mode']=matches[0]
  if not isinstance(r,dict) or type(r.get('final')) is not bool:
   checks.append(dict(event=index,kind='rpc_result',ok=False));break
  closed=r['final']
  if meta['family']=='aztecs-claw':
   phase=current.get('aztec_phase',0)
   if phase==0:
    incremental+=_win(r,meta['family'])
    if not closed and r['resp'].get('bonus_game')!='WILD_DICES':raise ValueError('Unknown Aztec trigger')
   elif phase==1:
    if r['resp'].get('bonus_game')!='WILD_DICES_FINISH':raise ValueError('Unknown Aztec bonus result')
    incremental+=_win(r,meta['family']);closed=False
   elif phase==2:
    if not closed:raise ValueError('Aztec finish acknowledgment did not close round')
   else:raise ValueError('Unexpected Aztec round phase')
   current['aztec_phase']=phase+1
  if meta['family'] in ('zeus-goes-wild','clash-gods') and r['resp']['super_spin']['bet']!=current['mode']['bet_native']:raise ValueError('Normalized-stage native response bet mismatch')
  if meta['family'] in ('jungle-queen','sugar-mix','treasure-explorer','keepers-secret','grand-patron'):incremental+=_win(r,meta['family'])
  if closed:
   win=incremental if meta['family'] in ('jungle-queen','sugar-mix','treasure-explorer','keepers-secret','grand-patron','aztecs-claw') else _win(r,meta['family']);expected=balance-current['mode']['cost_native']+win;actual=_money(r['balance'])
   checks.append(dict(event=index,kind='rpc_extra_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=r['balance'],ok=expected==actual))
   current.update(closed=True,last_event=index,cost_native=current['mode']['cost_native'],win_ratio=[win.numerator,win.denominator]);balance=actual;current=None;incremental=Fraction(0)
  previous=r
 return checks,rounds


def decode_static_strings(source):
 """Reproduce cached source string expansions without evaluating JavaScript.

 Only the obfuscator's literal string array and integer arithmetic checksum
 are interpreted. AST calls, attributes, names, subscripts and other Python
 constructs are rejected. The resulting source is research text, never code
 to execute. Callers must independently pin official original bytes by SHA256.
 """
 import ast
 import json
 import operator
 if not isinstance(source,str) or len(source)>10_000_000:raise ValueError('Static source size/type unsupported')
 arrays=list(re.finditer(r'const _0x\w+=\[(.*?)\];',source,re.S))
 offset_match=re.search(r'(_0x\w+)=\1-(0x[0-9a-f]+)',source)
 checksum_match=re.search(r'try\{const _0x\w+=(.*?);if\(',source)
 target_match=re.search(r'\}\((_0x\w+),(0x[0-9a-f]+)\)',source)
 if len(arrays)!=1 or not all((offset_match,checksum_match,target_match)):raise ValueError('Unsupported static string-table wrapper')
 try:values=ast.literal_eval('['+arrays[0].group(1)+']')
 except (ValueError,SyntaxError) as error:raise ValueError('Nonliteral static string array') from error
 if not values or len(values)>50000 or any(type(v) is not str for v in values):raise ValueError('Invalid static string array')
 offset=int(offset_match.group(2),16);target=int(target_match.group(2),16);checksum=checksum_match.group(1)
 operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
 def calculate(node):
  if isinstance(node,ast.Expression):return calculate(node.body)
  if isinstance(node,ast.Constant) and type(node.value) in (int,float):return Fraction(node.value)
  if isinstance(node,ast.UnaryOp) and type(node.op) in (ast.USub,ast.UAdd):return (-1 if isinstance(node.op,ast.USub) else 1)*calculate(node.operand)
  if isinstance(node,ast.BinOp) and type(node.op) in operations:return operations[type(node.op)](calculate(node.left),calculate(node.right))
  raise ValueError('Non-arithmetic static checksum')
 def parse_integer(match):
  index=int(match.group(1),16)-offset
  if index<0 or index>=len(values):raise ValueError('Static checksum index out of bounds')
  integer=re.match(r'^[+-]?\d+',values[index])
  if integer is None:raise ValueError('Static checksum NaN')
  return integer.group()
 for rotation in range(len(values)):
  try:
   expression=re.sub(r'parseInt\(_0x\w+\((0x[0-9a-f]+)\)\)',parse_integer,checksum)
   if calculate(ast.parse(expression,mode='eval'))==target:break
  except (ValueError,SyntaxError,ZeroDivisionError):pass
  values.append(values.pop(0))
 else:raise ValueError('Static string-table rotation checksum not resolved')
 def expand(match):
  index=int(match.group(1),16)-offset
  return json.dumps(values[index]) if 0<=index<len(values) else match.group()
 return re.sub(r'_0x\w+\((0x[0-9a-f]+)\)',expand,source)
