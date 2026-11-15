"""Three Kings Scratch native board/pack selectors and fixed raw bet."""
import hashlib
def metadata(source):
 tokens=['.data.totalBet=t.options.bet','.data.betMultiplier=t.options.bet_multipliers','additionalPlayData.mode=this.currentMode','additionalPlayData.purchased_feature="freespin_buy"','additionalPlayData.purchased_feature_level=`${t}`','rawPrice:i[t][e]*','this.freeSpinCommand="freespin"','bonus:!!','.data.additionalPlayData}})']
 if not all(t in source for t in tokens):raise ValueError('Scratch board/pack wire, cost or continuation not proved')
 return dict(scratch_packs_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Official board mode strings, fixed options.bet, normal bet_multipliers, pack rawPrice=freespin_buy_miltipliers[mode][count]*totalBet; purchase flags removed after confirmation, continuation uses freespin with same board/raw bet.',coverage_limit='Three boards and three explicitly advertised packs per board; insufficient native demo funds remain pending without local balance edits.')
def plan(initial,meta):
 o=initial['options'];c=o['currency'];raw=o['bet'];modes=o['available_modes'];multipliers=o['bet_multipliers'];packs=o['feature_options']['freespin_buy_miltipliers']
 if not meta.get('scratch_packs_verified') or c.get('code')!='FUN' or c.get('subunits')!=100 or type(raw) is not int or raw<=0 or set(modes)!={'12','16','20'} or set(packs)!=set(modes) or o['available_bets']!=[raw] or o['feature_options'].get('disabled_features'):raise ValueError('Unverified scratch FUN/pack schema')
 result=[]
 for board in modes:
  if set(packs[board])!={'10','50','100'}:raise ValueError('New scratch pack tier requires review')
  args={'bet':raw,'bonus':False,'mode':board};continuation=dict(args);normal=raw*multipliers[board]
  if type(normal) is not int or normal<=0:raise ValueError('Invalid scratch board price')
  result.append(dict(name='board:'+board,command='spin',options=args,cost_native=normal,continuation_options=continuation))
  for count,price in packs[board].items():
   if type(price) is not int or price<=0:raise ValueError('Noninteger scratch pack price')
   result.append(dict(name='board:'+board+'/pack:'+count,command='spin',options=dict(args,purchased_feature='freespin_buy',purchased_feature_level=count),cost_native=raw*price,continuation_options=continuation))
 return result
def cost(options,initial_options,command):
 if command=='freespin':return 0
 if command!='spin':raise ValueError('Unknown scratch audit action')
 board=options['mode'];bet=options['bet']
 if options.get('purchased_feature')=='freespin_buy':return bet*initial_options['feature_options']['freespin_buy_miltipliers'][board][options['purchased_feature_level']]
 return bet*initial_options['bet_multipliers'][board]
