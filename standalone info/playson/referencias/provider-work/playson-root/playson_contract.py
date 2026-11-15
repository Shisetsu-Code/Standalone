"""Observed Playson TEST XML quotes and closed-root financial reconciliation."""
import re,hashlib
from decimal import Decimal
from xml.etree import ElementTree as ET

def amount(value):
 if not isinstance(value,str)or not re.fullmatch(r'\d+',value):raise ValueError('Invalid minor-unit amount')
 return int(value)

def parse(text):
 if not isinstance(text,str)or len(text)>8*1024*1024 or '<!DOCTYPE'in text.upper()or '<!ENTITY'in text.upper():raise ValueError('Unsafe or oversized XML')
 r=ET.fromstring(text)
 if r.tag not in ['server','client']:raise ValueError('Unexpected XML root')
 return r

def quote(initial, native_multiplier=None, native_ante_multipliers=None):
 domain=initial.findtext('extra/stakeIncrement','');parts=domain.split(',');stakes=[amount(v)for v in parts]
 if not stakes or any(v<=0 for v in stakes):raise ValueError('Invalid stake domain')
 game=initial.find('game')
 if game is None:raise ValueError('Game quote absent')
 native=game.get('total_bet_mult');origin='server'
 if native is None and native_multiplier is not None:native=str(native_multiplier);origin='native_client_config'
 multiplier=amount(native or'')
 if multiplier<=0:raise ValueError('Native total-bet multiplier absent')
 buys=game.get('buy_feature_cost')or game.get('free_game_cost');prices=[]if buys is None else[amount(v)for v in buys.split(',')]
 if any(v<=0 for v in prices):raise ValueError('Invalid native purchase price')
 antes=[];ante_origin='server'
 native_domain=game.get('chance_booster','')
 if native_ante_multipliers is not None:
  values=[str(v)for v in native_ante_multipliers]
  if native_domain and [str(Decimal(v).normalize())for v in native_domain.split(',')if Decimal(v)>1]!=[str(Decimal(v).normalize())for v in values]:raise ValueError('Client ante domain conflicts with server')
  if not native_domain:native_domain=','.join(values);ante_origin='native_client_config'
 for value in native_domain.split(','):
  if not value:continue
  if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value)or Decimal(value)<=1:raise ValueError('Invalid ante multiplier')
  antes.append(str(Decimal(value).normalize()))
 return {'ante_domain_origin':ante_origin,'multiplier_origin':origin,'ante_multipliers':antes,'line_bet_minor':min(stakes),'line_bet_domain':stakes,'base_multiplier':multiplier,'base_cost_minor':min(stakes)*multiplier,'buy_multipliers':prices}

def snapshot(root,kind):
 state=root.find('state');wallet=root.find('user_new');game=root.find('game');bonus=root.find('bonus')
 return {'kind':kind,'command':root.get('command'),'status':root.get('status'),'state':state.get('current_state')if state is not None else None,'credit_minor':amount(wallet.get('cash'))if wallet is not None else None,'base_win_minor':amount(game.get('cash-win','0'))if game is not None else 0,'bonus_win_minor':amount(bonus.get('win','0'))if bonus is not None else 0,'bonus_present':bonus is not None,'bonus_spins_left':bonus.get('spins_left')if bonus is not None else None,'free_win_minor':amount(game.get('free-win'))if game is not None and game.get('free-win')is not None else None,'free_spins_remaining':amount(game.get('bonus_games'))if game is not None and game.get('bonus_games')is not None else None,'native_cash_bet_minor':amount(game.get('cash-bet'))if game is not None and game.get('cash-bet')is not None else None}

def settle(case):
 first=case['steps'][0];last=case['steps'][-1];free=[step for step in case['steps']if step['kind']=='free_bet']
 cash_win=sum(step['base_win_minor']for step in case['steps']if step['kind']in ['paid_entry','free_bet','cascade_next','player_choice']and not step.get('bonus_present',False))
 bonus_win=sum(step['bonus_win_minor']for step in case['steps']if (step.get('bonus_present',False)or step['kind']=='bonus')and step.get('bonus_spins_left')in ['0',None]and step['state']!='bonus')
 win=cash_win+bonus_win;terminal=last['state']=='idle'and last['status']in ['ok','bet']
 adjustments=case.get('demo_reconnect_adjustments',[]);adjustment=sum(v['delta_minor']for v in adjustments);valid_adjustments=all(v['kind']=='observed_test_reconnect_reset'and v['after_minor']==v['fixed_test_credit_minor']and v['delta_minor']==v['after_minor']-v['before_minor']for v in adjustments)and len({v['ordinal']for v in adjustments})==len(adjustments)
 checks={'documented_demo_adjustments':valid_adjustments,'positive_native_cost':case['cost_minor']>0,'entry_base_cost':case.get('entry_base_cost_matches',False),'entry_wallet':first['credit_minor']==case['before_minor']-case['cost_minor']+first['base_win_minor'],'wallet_ledger':last['credit_minor']==case['before_minor']-case['cost_minor']+win+adjustment,'round_closed':terminal,'purchase_binding':case.get('purchase_binding',True),'ante_binding':case.get('ante_binding',True),'free_entries_zero_cost':all(step.get('native_cash_bet_minor')==0 for step in free)}
 if free and last.get('free_win_minor')is not None:
  index=case['steps'].index(free[0]);paid=sum(step['base_win_minor']for step in case['steps'][index:]if step['kind']in ['free_bet','cascade_next']);case['native_free_counter_difference_minor']=last['free_win_minor']-paid;case['native_free_counter_minor']=last['free_win_minor'];case['free_micro_payout_minor']=paid
 case.update(demo_reconnect_adjustment_minor=adjustment,after_minor=last['credit_minor'],win_minor=win,cash_packet_win_minor=cash_win,bonus_packet_win_minor=bonus_win,checks=checks,passed=all(checks.values()));return case

def start_case(initial,reply,request,before,quote_data=None):
 q=quote_data if quote_data is not None else quote(initial);bet=request.find('bet');line=amount(bet.get('cash'))if bet is not None else 0
 if line not in q['line_bet_domain']:raise ValueError('Bet not in native stake domain')
 game=reply.find('game');buy=request.find('buy');index=None
 if game is None:raise ValueError('Missing native financial entry')
 base=line*q['base_multiplier'];cost=base;bound=True;ante=request.find('chance_booster');ante_value=None;ante_bound=True
 if buy is not None:
  prices=q['buy_multipliers'];index=amount(buy.get('type'))if buy.get('type')is not None else 0
  if buy.get('type')is None and len(prices)!=1:raise ValueError('Untyped purchase requires one native price')
  if index>=len(prices):raise ValueError('Unbound purchase index')
  cost*=prices[index];single=len(prices)==1;unique_price=len(set(prices))==len(prices);marker=game.get('bonus_game_type')=='bought'or (single or unique_price)and game.get('bonus_game_type')is None;subtype=game.get('bonus_game_sub_type')==str(index)or(single or unique_price)and game.get('bonus_game_sub_type')is None
  choice=reply.find('.//player_choice');choice_offered=reply.find('state')is not None and reply.find('state').get('current_state')=='choice'and choice is not None and bool(re.fullmatch('[0-9]+(?:,[0-9]+){0,9}',choice.get('types','')))
  bound=(buy.get('freegame')=='true'or buy.get('bonus_game')=='true')and marker and subtype and (reply.get('status')=='game'and choice_offered or reply.get('status')=='next'and reply.find('state')is not None and reply.find('state').get('current_state')=='respin'or reply.get('status')=='bonus'or reply.get('status')=='ok'and reply.find('state')is not None and(reply.find('state').get('current_state')=='bonus'or reply.find('state').get('current_state')=='fs'and amount(game.get('bonus_games','0'))>0))
 if ante is not None:
  if buy is not None:raise ValueError('Native ante/purchase mutual exclusion')
  ante_value=ante.get('type','');value=Decimal(ante_value)
  if value not in [Decimal(v)for v in q['ante_multipliers']]:raise ValueError('Ante not in native domain')
  price=Decimal(base)*value
  if price!=price.to_integral_value():raise ValueError('Fractional minor-unit price')
  cost=int(price);observed=game.get('chance_booster_type')
  if observed is None and game.get('ante_bet')in ['true','1']:observed=game.get('ante_bet_multiplier')
  ante_bound=observed is not None and Decimal(observed)==value
 mode='Ante:'+str(Decimal(ante_value).normalize())if ante_value is not None else'Spin'if index is None else'Buy:'+str(index)
 native_costs=(amount(game.get('cash-bet')),amount(game.get('cash-bet-game')))
 valid_costs=native_costs==(base,base)if ante_value is None and buy is None else all(v in [base,cost]for v in native_costs)
 return {'mode':mode,'kind':'ante'if ante_value is not None else'normal'if index is None else'purchase','before_minor':before,'line_bet_minor':line,'base_cost_minor':base,'cost_minor':cost,'multiplier':str(Decimal(ante_value).normalize())if ante_value is not None else 1 if index is None else q['buy_multipliers'][index],'minimum_observed':line==q['line_bet_minor'],'entry_base_cost_matches':valid_costs,'native_cash_bet_minor':native_costs[0],'native_cash_bet_game_minor':native_costs[1],'ante_binding':ante_bound,'purchase_binding':bound,'steps':[snapshot(reply,'paid_entry')]}

def reference_rounds(fixture):
 initial=parse(fixture['initial']);before=amount(initial.find('user_new').get('cash'));cases=[];active=None
 for packet in fixture['financial']:
  reply=parse(packet['response']);request=parse(packet['request'])
  if packet['path']=='/bet':
   if active is not None:raise ValueError('New paid entry before root closure')
   active=start_case(initial,reply,request,before)
  elif packet['path']=='/bonus':
   if active is None:raise ValueError('Bonus without accepted root')
   active['steps'].append(snapshot(reply,'bonus'))
  else:raise ValueError('Unreviewed financial command')
  before=active['steps'][-1]['credit_minor'];settle(active)
  if active['checks']['round_closed']:cases.append(active);active=None
 if active is not None:cases.append(settle(active))
 return cases
