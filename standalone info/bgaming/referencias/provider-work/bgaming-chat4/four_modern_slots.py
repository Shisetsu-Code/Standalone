"""Pinned native slot contracts. No network/session creation or source execution.

Parent hooks: load_metadata(gid, frontend_html, fetch(path)->bytes, allowed),
plan(initial_envelope, meta), run(hyper, mode), audit(initial, events, meta).
Use engine=four-modern-slots and protocol=jsonrpc-four-modern-slots.
"""
import copy,hashlib,json,re
from fractions import Fraction
from urllib.parse import urlsplit

PINS={'CatsLoveYummy': {'/public/main-CLI_bTL5.js': 'be3b766f0ce97ca4f7bcb2991c24caca49b595b0e4696b258b6b9f0fc08c8772', '/slot_assets/gameConfig.json': 'efb86fc0671d2d3d08b4c09173d51fc2943ba0cb5bd7635b7cfc8258f303ba88'}, 'RedHotChilliChickens': {'/main.js': '28652da884003877001e520669c43ca36dabf882c1e05a0df0812035c61c5602'}, 'ChickenFire': {'/assets/index-CoAzB5sA.js': '3447e6d2577faf09770c691dff91c15e10106981158b523080c99ac887c2ca33'}, 'MysticReels': {'/build/bpPlatformBGaming.js': '1e3fa6fe00d7b6692a485b12c87ffccb941ac03a38fe97c2dd5ceca080e473bb', '/build/platformBGaming.js': '113f693f13a72ba380c3aeb325a61c6ccd0d3b6bc6d7b2d9691e55a864cd2634', '/build/bpClientLibs.js': 'ec95c5fb936a090a9dee4e785f215f82a9743a1718b938ce636e16a41e9fb760', '/build/all.js': 'd377f9423317cf0bc268a0a34b2c964cfa3487f1a580bb9fffa706c458bb111d', '/lookup_table_1.0.18.json': '9b785b82e86f98e8cbdb513e3b16b926b42e771dd1861883470f83748b17d093', '/config/config.4d47dec95fae43ee37dd7fc68240022c0a4b41cf.json': '1657ee8e88c9ed3389c1b83bbb94e6c0f2182871e159c044547b5fc1a8a1ab2c'}}
PROTOCOL='jsonrpc-four-modern-slots'

def money(value):
 if type(value) not in (int,float) or isinstance(value,bool):raise ValueError('Native JSON number required')
 try:r=Fraction(str(value))
 except (ValueError,ZeroDivisionError):raise ValueError('Invalid native amount') from None
 if r<0:raise ValueError('Negative native amount')
 return r

def metadata(gid,sources,allowed):
 if gid not in PINS or set(sources)!=set(PINS[gid]):raise ValueError('Exact frontend source set required')
 for path,raw in sources.items():
  if not isinstance(raw,bytes) or hashlib.sha256(raw).hexdigest()!=PINS[gid][path]:raise ValueError('Fresh frontend source hash changed')
 text={path:raw.decode('utf8') for path,raw in sources.items()};source='\n'.join(text.values());products=[]
 def require(*tokens):
  if not all(token in source for token in tokens):raise ValueError('Pinned native source contract missing')
 if gid=='CatsLoveYummy':
  require('fetch(Fn("slot_assets/gameConfig.json"))','s={bet:e,bet_type:t,...i&&{purchased_feature:n.purchasedFeature,buy_feature_id:n.buyFeatureId}}','function l6(n){return o6(n)?"freebet":"bet"}','diffMoney:Number(e.win??e.winCredit??0)/t','const r=R.getTotalBet(R.betTableIndex);Z(On.REQ_SPIN,{betTotal:r})','const n=R,t=n.buyFeatureConfigs[0]','return e*i/(100n*VC)')
  cfg=json.loads(text['/slot_assets/gameConfig.json']);configs=cfg['buyFeatureInfo']['configs']
  if cfg.get('featureOnOff',{}).get('buyFeature') is not True or len(configs)!=1:raise ValueError('Buy-feature visibility changed')
  p=configs[0]
  if p!={'buyFeatureId':1,'purchasedFeature':'buy_bonus','pricePercent':10000}:raise ValueError('Native product registry changed')
  products=[dict(name='buy_feature:1',feature='buy_bonus',factor='100',extra={'purchased_feature':'buy_bonus','buy_feature_id':1})]
  evidence='Visible first source-registry config; pricePercent/100=100; native total bet plus bet_type=bet; resp.win is current step payout; free-spin state uses ordinary same-bet play without purchase.'
 elif gid=='RedHotChilliChickens':
  require('bet_type:"betting",action:"spin"','bet_type:"betting",action:"bonus"','isSuperBonus:1!==t,purchased_feature:"bonus_buy"','wager:t}=vx.getState().spinSlice,e=100*t,s=200*t','if(!f&&!1===w.final)','_.game.totalWin/v','I.result.resp.game.spin.totalWin/S')
  products=[dict(name='bonus_buy:'+name,feature='bonus_buy',factor=factor,extra={'purchased_feature':'bonus_buy','isSuperBonus':flag}) for name,factor,flag in [('normal','100',False),('super','200',True)]]
  evidence='Two explicit UI purchases100x/200x; isSuperBonus boolean; initial action spin omitted for purchase; pending BONUS completes via one bonus action; final bonus game.totalWin versus ordinary spin.totalWin.'
 elif gid=='MysticReels':
  require('"bet_type": self._isPrePaidGame ? "freebet" : "bet"','"bet": self._stake','request.bet = (request.bet * 2) / 3','request.bet /= 100','if (!this._inGame) // only specify purchased_feature first spin','self.totalGameWinnings += resp.result.resp.CashWin','self.getSpinData(cb, resp.result.resp, resp.result.final)','BPloader.loadFile( "config/config.json"','return this._assetTable.table[resourceName]','let filename = "lookup_table_" +  gameData.gameVersionMajor','gameData.gameVersionMajor = "1"','gameData.gameVersionMinor = "0"','gameData.gameVersionBugFix = "18"')
  table=json.loads(text['/lookup_table_1.0.18.json']);route='/'+table['table']['config/config.json'].lstrip('/')
  if route!='/config/config.4d47dec95fae43ee37dd7fc68240022c0a4b41cf.json':raise ValueError('Native resource mapping changed')
  cfg=json.loads(text[route]);controller=[c for c in cfg['controllers'] if c['type']=='GameModeController']
  if len(controller)!=1:raise ValueError('Native mode controller ambiguous')
  modes=controller[0]['modes']
  if [(m['name'],str(m['ante']),m['platformNameMap']['bGaming']['name']) for m in modes]!=[('BASIC','1','BASIC'),('ENCORE','1.5','RESPIN_BUY'),('BONUSBUY1','100','BONUS_BUY')]:raise ValueError('Visible native modes changed')
  products=[dict(name='ENCORE',feature='buy_chance',factor='1.5',extra={'purchased_feature':'buy_chance'}),dict(name='BONUSBUY1',feature='buy_bonus',factor='100',extra={'purchased_feature':'buy_bonus'})]
  evidence='Versioned lookup selects UI mode controller BASIC1/ENCORE1.5/BONUSBUY100; native wire reverses UI multiplier to original bet; feature only first request; all automatic steps use same bet; CashWin incremented into totalGameWinnings.'
 else:
  require('KP=new bi,JP=1.5,QP={buy_bonus:60,buy_super_bonus:90,buy_ultra_bonus:120}','featureId:"buy_bonus"','featureId:"buy_super_bonus"','featureId:"buy_ultra_bonus"','purchased_feature:"buy_bonus",feature_id:t.featureId,featureSelectionPopupOpen:!1,buyChance:!1','req:t})).result','i=await NI(e,qP.stateLock)','qP.gameResponse=i.resp,qP.balanceAfter=i.balance','qP.gameResponse?.totalWin??0','this.gsm.changeState(this.gsm.prespinState)','const t=tM(),e=await NI(t,qP.stateLock);qP.stateLock=e.state_lock,qP.balanceAfter=e.balance,$P.setState({freebets:e.freebets}),i=e.final','i?this.gsm.changeState(this.gsm.bonusOutroState):($P.setState({spinStageIndex:t.spinStageIndex+1})')
  products=[dict(name='buy_chance',feature='buy_chance',factor='1.5',extra={'purchased_feature':'buy_chance'})]+[dict(name=key,feature='buy_bonus',factor=str(factor),extra={'purchased_feature':'buy_bonus','feature_id':key}) for key,factor in [('buy_bonus',60),('buy_super_bonus',90),('buy_ultra_bonus',120)]]
  evidence='Explicit UI chance1.5 and three literal feature IDs60/90/120; purchase disables chance. Initial play retains gameResponse resp.data and totalWin for the whole round. Bonus showWinnings sends plain tM() bet/bet_type after each visual stage, updates only balance/state_lock/freebets/final, then increments stage until final. Initial totalWin is counted once; continuation resp never replaces gameResponse.'
 products=[p for p in products if p['feature'] in allowed]
 refs=[dict(path=path,sha256=sha) for path,sha in PINS[gid].items()];identity=hashlib.sha256(json.dumps(refs,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return dict(game_id=gid,engine='four-modern-slots',protocol=PROTOCOL,source_verified=True,source_sha256=identity,source_refs=refs,products=products,evidence=evidence,unresolved=[],**({'chicken_bonus_stage_verified':True} if gid=='ChickenFire' else {}))

def load_metadata(gid,frontend,fetch,allowed):
 if gid not in PINS:raise ValueError('Unsupported fresh slot frontend')
 html=frontend.decode('utf8') if isinstance(frontend,bytes) else frontend
 selected={urlsplit(path).path.removeprefix('./') for path in re.findall(r'<script[^>]+src=["\']([^"\']+)',html) if not urlsplit(path).scheme and not urlsplit(path).netloc and '..' not in urlsplit(path).path.split('/')}
 for path in PINS[gid]:
  if path.endswith('.js') and not any(p.lstrip('/')==path.lstrip('/') for p in selected):raise ValueError('Fresh HTML no longer selects pinned source')
 return metadata(gid,{path:fetch(path) for path in PINS[gid]},allowed)

def plan(initial,meta):
 r=initial['result'];a=r['currency_attributes'];bets=r['config']['bet_limits']
 if not meta.get('source_verified') or r.get('currency')!='FUN' or a.get('code')!='FUN' or a.get('subunits')!=100 or a.get('exponent')!=2 or r.get('state') is not None or r.get('freebets') or not bets or any(type(b) is not int or b<=0 for b in bets):raise ValueError('Native FUN fresh modern-slot init required')
 if any(p['feature'] not in r['config'].get('purchased_features',[]) for p in meta['products']):raise ValueError('Current init no longer permits prepared native product')
 money(r['balance']);bet=min(bets);out=[]
 for p in [dict(name='normal',factor='1',extra={})]+meta['products']:
  cost=bet*Fraction(p['factor'])
  if cost.denominator!=1:raise ValueError('Native price is fractional; no scaled bet substituted')
  req={'bet':bet,'bet_type':'betting' if meta['game_id']=='RedHotChilliChickens' else 'bet'}
  if meta['game_id']=='RedHotChilliChickens' and p['name']=='normal':req['action']='spin'
  req.update(p['extra'])
  out.append(dict(name=p['name'],protocol=PROTOCOL,game_id=meta['game_id'],req=req,bet_native=bet,cost_native=int(cost),source_sha256=meta['source_sha256']))
 return out

def _body(value):
 if isinstance(value,str):value=json.loads(value)
 if not isinstance(value,dict):raise ValueError('Native bonus object missing')
 return value

def continuation(gid,result,bet,opening=None,completed_stages=0):
 if result.get('final') is not False:raise ValueError('Continuation requires explicit nonfinal flag')
 if gid=='ChickenFire':
  base=(opening or result)['resp'];data=base.get('data')
  if base.get('baseBet')!=bet or base.get('stageIndex')!=0 or not isinstance(data,list) or not 0<len(data)<500 or not 0<=completed_stages<len(data) or any(not isinstance(stage,dict) or type(stage.get('respinsCount')) is not int or stage['respinsCount']<0 for stage in data):raise ValueError('Unknown/exhausted ChickenFire bonus stage contract')
  return {'bet':bet,'bet_type':'bet'}
 resp=result['resp']
 if gid=='RedHotChilliChickens':
  if resp.get('nextAction')!='BONUS':raise ValueError('Unknown pending RedHot nextAction')
  return {'bet':bet,'bet_type':'betting','action':'bonus'}
 if gid=='CatsLoveYummy':
  body=_body(resp['body']);current=_body(body.get('currentBonus') or {});nxt=_body(body.get('nextBonus') or {})
  pending='free' in str(nxt.get('bonusName','')) or ('free' in str(current.get('bonusName','')) and current.get('currentSpin',current.get('spinIndex',0))<current.get('totalSpins',current.get('totalSpinCount',0)))
  if not pending:raise ValueError('Unknown pending Cats bonus; no new paid spin')
 return {'bet':bet,'bet_type':'bet'}

def step_win(gid,result,request):
 resp=result['resp']
 if gid=='CatsLoveYummy':return money(resp.get('win',resp.get('winCredit',0)))
 if gid=='MysticReels':return money(resp['CashWin'])
 if gid=='ChickenFire':
  if not isinstance(resp.get('data'),list) or not resp['data']:raise ValueError('ChickenFire complete native stage array missing')
  return money(resp['totalWin'])
 return money(resp['game']['totalWin'] if request.get('action')=='bonus' else resp['game']['spin']['totalWin'])

def chicken_stage_check(before,after,ceiling):
 low=before if isinstance(before,Fraction) else money(before);high=ceiling if isinstance(ceiling,Fraction) else money(ceiling);actual=money(after)
 return dict(kind='chicken_native_zero_debit_stage',minimum_ratio=[low.numerator,low.denominator],maximum_ratio=[high.numerator,high.denominator],actual_native=after,ok=low<=actual<=high)

def finish_chicken_received(h,mode,*,before_native,opening,start_event):
 """Continue one already received round; this function never resends its purchase."""
 if mode not in plan(h.initial,h.metadata) or mode['game_id']!='ChickenFire' or not h.metadata.get('chicken_bonus_stage_verified') or h.last!=opening:raise ValueError('Source/received ChickenFire context differs')
 before=before_native if isinstance(before_native,Fraction) else money(before_native);win=step_win('ChickenFire',opening,mode['req']);expected=before-mode['cost_native']+win;current=opening;round_id=opening.get('round');completed=0;previous=before-mode['cost_native']
 while True:
  if type(current.get('final')) is not bool:raise ValueError('Native Chicken final flag missing')
  stage_check=chicken_stage_check(previous,current['balance'],expected);h.parent.money_checks.append(stage_check)
  if not stage_check['ok']:raise ValueError('Native Chicken stage debited or exceeded original total win; no retry')
  previous=money(current['balance'])
  if current['final']:
   ok=previous==expected;h.parent.money_checks.append(dict(kind='four_modern_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=current['balance'],cost_native=mode['cost_native'],win_ratio=[win.numerator,win.denominator],ok=ok))
   if not ok:raise ValueError('Native Chicken final wallet differs from initial total win')
   return dict(mode=mode,status='closed',first_event=start_event,last_event=len(h.parent.events)-1,final_balance=current['balance'],final_state='final',win_ratio=[win.numerator,win.denominator],bonus_continuation_requests=completed)
  req=continuation('ChickenFire',current,mode['bet_native'],opening,completed)
  current=h.request('play',req)['result'];completed+=1
  if current.get('round')!=round_id:raise ValueError('Native Chicken continuation changed round')

def run(h,mode):
 if mode not in plan(h.initial,h.metadata):raise ValueError('Mode differs from source-native initialized plan')
 gid=mode['game_id'];before=money(h.last['balance']);cost=mode['cost_native'];bet=mode['bet_native'];start=len(h.parent.events)
 if mode['protocol']!=PROTOCOL or h.last.get('final') is False or (h.last.get('state') is not None and 'final' not in h.last):raise ValueError('Unproved or already open modern slot round')
 if before<cost:return dict(mode=mode,status='insufficient_demo_balance')
 if gid=='ChickenFire':
  opening=h.request('play',copy.deepcopy(mode['req']))['result']
  return finish_chicken_received(h,mode,before_native=before,opening=opening,start_event=start)
 req=copy.deepcopy(mode['req']);win=Fraction(0);round_id=None
 for count in range(500):
  result=h.request('play',req)['result']
  if type(result.get('final')) is not bool or not isinstance(result.get('resp'),dict):raise ValueError('Modern slot result/final schema changed')
  if count==0:round_id=result.get('round')
  elif result.get('round')!=round_id:raise ValueError('Native continuation changed round identity')
  payout=step_win(gid,result,req);win=win+payout if gid in ('CatsLoveYummy','MysticReels') else payout
  if result['final']:
   expected=before-cost+win;actual=money(result['balance']);ok=actual==expected;h.parent.money_checks.append(dict(kind='four_modern_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=result['balance'],cost_native=cost,win_ratio=[win.numerator,win.denominator],ok=ok))
   if not ok:raise ValueError('Native modern slot balance mismatch; no next round')
   return dict(mode=mode,status='closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=result['balance'],final_state='final',win_ratio=[win.numerator,win.denominator])
  if gid=='RedHotChilliChickens' and req.get('action')=='bonus':raise ValueError('RedHot bonus completion was not final; no repeat')
  req=continuation(gid,result,bet)
 raise ValueError('Modern slot continuation bound exhausted; pending receipt retained')

def audit(initial,events,meta):
 modes=plan(initial,meta);balance=money(initial['result']['balance']);checks=[];rounds=[];current=None;gid=meta['game_id']
 for index,event in enumerate(events):
  if event.get('request',{}).get('method')!='play':continue
  try:
   request=event['request']['params']['req'];result=event['response']['result']
   if event.get('status')!=200 or type(result.get('final')) is not bool:raise ValueError('Rejected/uncertain native receipt')
   if current is None:
    matches=[m for m in modes if m['req']==request]
    if len(matches)!=1:raise ValueError('Unproved native opening request')
    mode=matches[0];current=dict(start_event=index,cost_native=mode['cost_native'],before_ratio=[balance.numerator,balance.denominator],closed=False,mode_name=mode['name'],round=result.get('round'));rounds.append(current);win=Fraction(0);opening=result;completed=0;previous=balance-mode['cost_native']
   else:
    if request!=next_req or result.get('round')!=current['round']:raise ValueError('Native continuation request/round differs')
    completed+=1
   if gid!='ChickenFire' or completed==0:
    payout=step_win(gid,result,request);win=win+payout if gid in ('CatsLoveYummy','MysticReels') else payout
   if gid=='ChickenFire':
    check=chicken_stage_check(previous,result['balance'],Fraction(*current['before_ratio'])-current['cost_native']+win);checks.append(dict(event=index,**check));previous=money(result['balance'])
    if not check['ok']:raise ValueError('Chicken native stage debit/win bound failed')
   if result['final']:
    before=Fraction(*current['before_ratio']);expected=before-current['cost_native']+win;actual=money(result['balance']);checks.append(dict(event=index,kind='four_modern_native_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=result['balance'],ok=expected==actual));current.update(closed=True,end_event=index,final_balance_native=result['balance'],win_ratio=[win.numerator,win.denominator]);balance=actual;current=None
   else:
    if gid=='RedHotChilliChickens' and request.get('action')=='bonus':raise ValueError('Repeated RedHot completion forbidden')
    next_req=continuation(gid,result,mode['bet_native'],opening,completed)
  except (ValueError,KeyError,TypeError,AttributeError):checks.append(dict(event=index,kind='four_modern_native_contract',ok=False));break
 if current is not None:checks.append(dict(kind='four_modern_open_round',start_event=current['start_event'],mode_name=current['mode_name'],reason='Saved native round has no verified final response',ok=False))
 return checks,rounds
